import { spawn, spawnSync } from 'node:child_process';
import readline from 'node:readline/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createActionController } from './actions.mjs';
import { runAccountCli } from './account-cli.mjs';
import { cliToolStatus, setupCliTools } from './cli-tools.mjs';
import { collectStatus } from './status.mjs';
import { startServer } from './server.mjs';
import { setupEnvironment } from './setup.mjs';
import { runGuidance } from './guidance.mjs';
import { runTui } from './tui.mjs';
import { runTask } from './tasks.mjs';
import { checkAgents, deployAgents, planAgents, agentsStatus } from './agents.mjs';
import { configureWorkspaceMcp, workspaceMcpCommand, workspaceMcpStatus, readWorkspaceMcpConfig, workspaceMcpPaths } from './workspace-mcp.mjs';

const rawCommand = process.argv[2] || null;
const command = rawCommand === '--accounts' || rawCommand === '--account-status' ? 'account' : rawCommand;
const host = process.env.AICC_HOST || '127.0.0.1';
const port = Number(process.env.AICC_PORT || 4381);
const url = `http://${host}:${port}`;

function help() {
  console.log(`AI Control Center (aicc)

Usage:
  aicc                  검색 가능한 대화형 메뉴 열기
  aicc menu             검색 가능한 대화형 메뉴 열기
  aicc setup [--check]  개인 설정 파일 생성 또는 설치 상태 점검
  aicc status [--json]  현재 구성 요소 상태 조회
  aicc account          시각적 GPT 계정 관리 메뉴
  aicc account status [--json]
                       기본 GPT Desktop 계정 상태
  aicc account ocx list|current [--json]
                       OCX 라우팅 계정 상태
  aicc account portal status|open [--json]
                       웹 로그인 전달 포털 확인 또는 열기
  aicc start            로컬 관리 화면 실행
  aicc open             로컬 화면을 실행하고 브라우저에서 열기
  aicc agents plan|deploy|check|status
                       AICC 정본 Codex 하위 에이전트 관리
  aicc workspace configure|status|serve
                       Secure Tunnel용 로컬 워크스페이스 MCP 관리
  aicc guidance plan    Codex·Claude 지침 배포 변경 미리보기
  aicc guidance deploy  AICC 정본 지침과 스킬을 두 홈에 배포
  aicc guidance check   정본·배포본·manifest 정합성 검사
  aicc cli status       codex·claude·OCX CLI 연결 상태 확인
  aicc cli setup [--install-missing]
                       고정 버전 CLI 설치와 OCX 연결 설정
  aicc action list      허용된 제어 작업 조회
  aicc action preview <작업> [--selector <계정>]
                       변경 내용 미리보기와 확인 토큰 발급
  aicc action execute --confirmation <토큰>
                       미리 본 작업을 한 번 실행하고 결과 확인
  aicc help             도움말

호환: cm ... = aicc account ... · aicc --accounts · aicc --account-status

Actions: ocx.start, ocx.sync, ocx.stop, account.switch, ocx.account.use, ocx.account.import-cm`);
}

async function ask(question) {
  const prompt = readline.createInterface({ input: process.stdin, output: process.stdout });
  try { return (await prompt.question(question)).trim(); }
  finally { prompt.close(); }
}

async function interactiveAction(name, suppliedArgs = {}) {
  const controller = createActionController();
  let args = { ...suppliedArgs };
  if (name === 'account.switch' && !args.selector) {
    const status = await collectStatus();
    const accountComponent = status.components.find(component => component.id === 'accounts');
    const available = (accountComponent?.accounts ?? []).filter(account => !account.expired && !account.is_app_active);
    if (!available.length) throw new Error('전환할 수 있는 다른 계정이 없습니다.');
    console.log('\n전환할 계정');
    available.forEach((account, index) => console.log(`  ${index + 1}. ${account.account} (${account.plan || '요금제 미확인'})`));
    const selected = Number(await ask('번호를 선택하세요: '));
    if (!Number.isInteger(selected) || !available[selected - 1]) throw new Error('올바른 번호를 선택하지 않았습니다.');
    args = { selector: available[selected - 1].account };
  }
  if (name === 'ocx.account.use' && !args.selector) {
    const status = await collectStatus();
    const component = status.components.find(item => item.id === 'ocx-accounts');
    const available = (component?.accounts ?? []).filter(account => !account.active && !account.needsReauth && !account.paused);
    if (!available.length) throw new Error('전환할 수 있는 다른 OCX 계정이 없습니다.');
    console.log('\n새 작업에 사용할 OCX 계정');
    available.forEach((account, index) => {
      console.log(`  ${index + 1}. ${account.label || account.email || account.id} (${account.plan || '요금제 미확인'})`);
    });
    const selected = Number(await ask('번호를 선택하세요: '));
    if (!Number.isInteger(selected) || !available[selected - 1]) throw new Error('올바른 번호를 선택하지 않았습니다.');
    args = { selector: available[selected - 1].id };
  }
  const preview = await controller.preview(name, args);
  console.log(`\n${preview.title}\n${preview.impact}`);
  for (const warning of preview.warnings ?? []) console.log(`주의: ${warning}`);
  console.log(`복구: ${preview.rollback}`);
  const answer = (await ask('실행할까요? [y/N] ')).toLocaleLowerCase();
  if (!['y', 'yes', '예'].includes(answer)) {
    console.log('취소했습니다.');
    return;
  }
  printJsonOrSummary(await controller.execute(preview.confirmationToken));
}

async function executeMenuItem(item) {
  if (item.action) return interactiveAction(item.action);
  if (item.confirm) {
    const answer = (await ask(`${item.title}을(를) 실행할까요? [y/N] `)).toLocaleLowerCase();
    if (!['y', 'yes', '예'].includes(answer)) return console.log('취소했습니다.');
  }
  const parts = item.command.split(' ');
  const executable = parts.shift();
  const invocation = executable === 'aicc'
    ? [process.execPath, [process.argv[1], ...parts]]
    : [executable, parts];
  const result = spawnSync(invocation[0], invocation[1], { stdio: 'inherit', env: process.env, cwd: process.cwd() });
  if (result.error) throw result.error;
  if (result.status && result.status !== 0) console.log(`명령이 종료 코드 ${result.status}로 끝났습니다.`);
}

function optionValue(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}

function printJsonOrSummary(result) {
  if (process.argv.includes('--json')) console.log(JSON.stringify(result, null, 2));
  else if (result.confirmationToken) {
    console.log(`${result.title}\n${result.impact}`);
    for (const warning of result.warnings ?? []) console.log(`주의: ${warning}`);
    console.log(`복구: ${result.rollback}`);
    console.log(`확인 토큰: ${result.confirmationToken}`);
    console.log(`유효 시각: ${result.expiresAt}`);
  } else {
    console.log(`${result.ok ? '✓' : '!'} ${result.title}: ${result.message}`);
    if (result.command?.output) console.log(result.command.output);
  }
}

function printSetup(result) {
  if (process.argv.includes('--json')) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  console.log(`${result.ok ? '✓' : '!'} 개인 설정: ${result.file}${result.created ? ' (생성됨)' : ''}`);
  console.log(`${result.security.ok && result.syntax.ok ? '✓' : '!'} 설정 파일: ${result.syntax.detail || result.security.reason}`);
  for (const check of result.checks) {
    console.log(`${check.ok ? '✓' : check.required ? '!' : '○'} ${check.name}: ${check.detail}${check.required ? '' : ' (선택)'}`);
  }
}

function printCliStatus(result) {
  if (process.argv.includes('--json')) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  for (const [name, state] of Object.entries(result.commands)) {
    console.log(`${state.available ? '✓' : '!'} ${name}: ${state.version || '설치되지 않음'}`);
  }
  console.log(`${result.proxyReady ? '✓' : '!'} OCX 연결: ${result.proxyReady ? '준비됨' : '준비되지 않음'}`);
  console.log(`${result.codexConnected ? '✓' : '!'} codex 라우팅: ${result.codexConnected ? 'OCX 연결됨' : '연결되지 않음'}`);
  console.log(result.note);
  if (result.installed?.length) console.log(`설치됨: ${result.installed.join(', ')}`);
  if (result.installCommand && result.missing?.length) console.log(`설치: ${result.installCommand}`);
}

function printTaskResult(result) {
  if (process.argv.includes('--json')) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  console.log(`${result.ok ? '✓' : '!'} ${result.title} (${result.durationMs}ms)`);
  if (result.result !== null && result.result !== undefined) {
    console.log(typeof result.result === 'string' ? result.result : JSON.stringify(result.result, null, 2));
  }
}

function openBrowser(target) {
  const platformCommand = process.platform === 'darwin'
    ? ['open', [target]]
    : process.platform === 'win32'
      ? ['cmd.exe', ['/d', '/s', '/c', 'start', '', target]]
      : ['xdg-open', [target]];
  const child = spawn(platformCommand[0], platformCommand[1], {
    detached: true,
    stdio: 'ignore',
    windowsHide: true
  });
  child.unref();
}

async function isReachable(target) {
  try {
    const response = await fetch(target, { signal: AbortSignal.timeout(800), cache: 'no-store' });
    return response.ok;
  } catch { return false; }
}

async function main() {
  if (!command || command === 'menu') {
    if (process.stdin.isTTY && process.stdout.isTTY) {
      await runTui({ execute: executeMenuItem });
    } else help();
    return;
  }
  if (command === 'account') {
    const args = rawCommand === '--account-status' ? ['status', '--json'] : process.argv.slice(3);
    if (args[0] === 'ocx' && args[1] === 'use') {
      const selector = args[2];
      if (!selector) throw new Error('사용할 OCX 계정 ID가 필요합니다.');
      if (process.stdin.isTTY && process.stdout.isTTY) {
        await interactiveAction('ocx.account.use', { selector });
      } else {
        const preview = await createActionController().preview('ocx.account.use', { selector });
        printJsonOrSummary(preview);
      }
      return;
    }
    const code = await runAccountCli(args);
    if (code !== 0) process.exitCode = code;
    return;
  }
  if (command === 'setup') {
    const result = await setupEnvironment({ checkOnly: process.argv.includes('--check') });
    printSetup(result);
    if (!result.ok) process.exitCode = 1;
    return;
  }
  if (command === 'status') {
    const status = await collectStatus();
    if (process.argv.includes('--json')) console.log(JSON.stringify(status, null, 2));
    else {
      console.log(`AI Control Center · 조회 전용 · ${status.summary.ready}/${status.summary.total} 준비됨`);
      for (const component of status.components) {
        const mark = component.state === 'ready' ? '✓' : component.state === 'offline' ? '○' : '!';
        console.log(`${mark} ${component.label}: ${component.detail}`);
      }
    }
    return;
  }
  if (command === 'guidance') {
    const subcommand = process.argv[3] || 'check';
    runGuidance(subcommand);
    return;
  }
  if (command === 'agents') {
    const subcommand = process.argv[3] || 'status';
    const result = subcommand === 'plan' ? planAgents()
      : subcommand === 'deploy' ? deployAgents()
        : subcommand === 'check' ? checkAgents()
          : subcommand === 'status' ? agentsStatus()
            : null;
    if (!result) throw new Error(`알 수 없는 agents 명령: ${subcommand}`);
    if (process.argv.includes('--json')) console.log(JSON.stringify(result, null, 2));
    else console.log(`${result.ok ? '✓' : '!'} ${result.message}`);
    if (result.ok === false) process.exitCode = 1;
    return;
  }
  if (command === 'workspace') {
    const subcommand = process.argv[3] || 'status';
    if (subcommand === 'configure') {
      const result = configureWorkspaceMcp();
      if (process.argv.includes('--json')) console.log(JSON.stringify(result, null, 2));
      else console.log(`✓ Workspace MCP에 Git 워크스페이스 ${result.workspaceCount}개를 등록했습니다.`);
      return;
    }
    if (subcommand === 'status') {
      const result = await workspaceMcpStatus();
      if (process.argv.includes('--json')) console.log(JSON.stringify(result, null, 2));
      else console.log(`${result.state === 'ready' ? '✓' : '!'} ${result.detail}`);
      if (result.state !== 'ready') process.exitCode = 1;
      return;
    }
    if (subcommand === 'serve') {
      const config = readWorkspaceMcpConfig();
      if (!config) throw new Error('먼저 aicc workspace configure를 실행해야 합니다.');
      const details = workspaceMcpCommand(config, { configPath: workspaceMcpPaths().config });
      const child = spawn(details.executable, details.args, { cwd: details.cwd, env: process.env, stdio: 'inherit', windowsHide: true });
      child.once('exit', code => { process.exitCode = code ?? 1; });
      return;
    }
    throw new Error(`알 수 없는 workspace 명령: ${subcommand}`);
  }
  if (command === 'start') {
    startServer();
    return;
  }
  if (command === 'open') {
    if (!await isReachable(`${url}/healthz`)) {
      const script = fileURLToPath(new URL('./server.mjs', import.meta.url));
      const child = spawn(process.execPath, [script], {
        detached: true,
        stdio: 'ignore',
        cwd: path.dirname(script),
        env: process.env,
        windowsHide: true
      });
      child.unref();
      await new Promise(resolve => setTimeout(resolve, 350));
    }
    openBrowser(url);
    console.log(`AI Control Center를 여는 중입니다: ${url}`);
    return;
  }
  if (command === 'cli') {
    const subcommand = process.argv[3] || 'status';
    const result = subcommand === 'status'
      ? await cliToolStatus()
      : subcommand === 'setup'
        ? await setupCliTools({ installMissing: process.argv.includes('--install-missing') })
        : null;
    if (!result) throw new Error(`알 수 없는 cli 명령: ${subcommand}`);
    printCliStatus(result);
    if (!result.ok) process.exitCode = 1;
    return;
  }
  if (command === 'action') {
    const controller = createActionController();
    const actionCommand = process.argv[3] || 'list';
    if (actionCommand === 'list') {
      const actions = controller.list();
      if (process.argv.includes('--json')) console.log(JSON.stringify({ ok: true, actions }, null, 2));
      else for (const action of actions) console.log(`${action.name}\t${action.title}`);
      return;
    }
    if (actionCommand === 'preview') {
      const actionName = process.argv[4];
      if (!actionName) throw new Error('미리 볼 작업 이름이 필요합니다.');
      printJsonOrSummary(await controller.preview(actionName, { selector: optionValue('--selector') }));
      return;
    }
    if (actionCommand === 'execute') {
      const confirmationToken = optionValue('--confirmation');
      if (!confirmationToken) throw new Error('--confirmation 토큰이 필요합니다.');
      const result = await controller.execute(confirmationToken);
      printJsonOrSummary(result);
      if (!result.ok) process.exitCode = 1;
      return;
    }
    throw new Error(`알 수 없는 action 명령: ${actionCommand}`);
  }
  help();
  process.exitCode = 2;
}

main().catch(error => {
  console.error(`aicc: ${error.message}`);
  process.exitCode = 1;
});
