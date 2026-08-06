import readline from 'node:readline';
import { searchCatalog } from './catalog.mjs';

const ansi = {
  clear: '\u001b[2J\u001b[H', hide: '\u001b[?25l', show: '\u001b[?25h',
  reset: '\u001b[0m', dim: '\u001b[2m', bold: '\u001b[1m', green: '\u001b[38;5;115m',
  cyan: '\u001b[38;5;117m', gray: '\u001b[38;5;245m', inverse: '\u001b[7m'
};

function clip(value, width) {
  const text = String(value);
  if (text.length <= width) return text;
  return `${text.slice(0, Math.max(1, width - 1))}…`;
}

export function renderMenu({ query = '', selected = 0, columns = 90, rows = 28 } = {}) {
  const items = searchCatalog(query);
  const width = Math.max(44, Math.min(columns, 100));
  const lines = [
    `${ansi.bold}${ansi.green}AICC${ansi.reset}  AI 도구를 검색하고 바로 실행하세요`,
    `${ansi.dim}↑↓ 이동  Enter 실행  글자 입력 검색  Backspace 지우기  Esc 종료${ansi.reset}`,
    '',
    `${ansi.cyan}검색${ansi.reset}  ${query || `${ansi.dim}도구 이름이나 할 일을 입력하세요${ansi.reset}`}`,
    `${ansi.gray}${'─'.repeat(width)}${ansi.reset}`
  ];
  if (!items.length) {
    lines.push('', '  일치하는 도구가 없습니다. Backspace로 검색어를 줄여보세요.');
    return { text: lines.join('\n'), items };
  }
  const visibleCount = Math.max(3, Math.floor((Math.max(12, rows) - 8) / 2));
  const selectedIndex = Math.min(selected, items.length - 1);
  const start = Math.max(0, Math.min(selectedIndex - Math.floor(visibleCount / 2), items.length - visibleCount));
  const visibleItems = items.slice(start, start + visibleCount);
  if (start > 0) lines.push(`${ansi.dim}  ↑ 위에 ${start}개 더 있음${ansi.reset}`);
  visibleItems.forEach((item, visibleIndex) => {
    const index = start + visibleIndex;
    const active = index === Math.min(selected, items.length - 1);
    const marker = active ? `${ansi.green}›${ansi.reset}` : ' ';
    const title = active ? `${ansi.bold}${item.title}${ansi.reset}` : item.title;
    lines.push(`${marker} ${title}`);
    lines.push(`  ${ansi.dim}${clip(item.description, width - 4)}${ansi.reset}`);
    if (active) lines.push(`  ${ansi.cyan}${item.command}${ansi.reset}`);
  });
  const remaining = items.length - (start + visibleItems.length);
  if (remaining > 0) lines.push(`${ansi.dim}  ↓ 아래에 ${remaining}개 더 있음${ansi.reset}`);
  return { text: lines.join('\n'), items };
}

export async function runTui(options = {}) {
  const input = options.input ?? process.stdin;
  const output = options.output ?? process.stdout;
  const execute = options.execute ?? (async () => {});
  if (!input.isTTY || !output.isTTY) return false;
  readline.emitKeypressEvents(input);
  let query = '';
  let selected = 0;
  let active = true;
  const draw = () => {
    const view = renderMenu({ query, selected, columns: output.columns ?? 90, rows: output.rows ?? 28 });
    selected = Math.min(selected, Math.max(0, view.items.length - 1));
    output.write(`${ansi.clear}${ansi.hide}${view.text}`);
    return view.items;
  };
  const cleanup = () => {
    if (input.setRawMode) input.setRawMode(false);
    output.write(`${ansi.show}${ansi.reset}\n`);
  };
  input.setRawMode(true);
  input.resume();
  let items = draw();
  try {
    while (active) {
      const event = await new Promise(resolve => input.once('keypress', (character, key) => resolve({ character, key })));
      const { character, key } = event;
      if (key?.ctrl && key.name === 'c' || key?.name === 'escape' || (!query && character === 'q')) break;
      if (key?.name === 'up') selected = Math.max(0, selected - 1);
      else if (key?.name === 'down') selected = Math.min(Math.max(0, items.length - 1), selected + 1);
      else if (key?.name === 'backspace') { query = query.slice(0, -1); selected = 0; }
      else if (key?.name === 'return' && items[selected]) {
        const item = items[selected];
        cleanup();
        await execute(item);
        if (!input.isTTY) return true;
        output.write(`\n${ansi.dim}계속하려면 아무 키나 누르세요.${ansi.reset}`);
        input.setRawMode(true);
        await new Promise(resolve => input.once('keypress', resolve));
        selected = 0;
      } else if (character && !key?.ctrl && !key?.meta && character >= ' ') {
        query += character;
        selected = 0;
      }
      items = draw();
    }
  } finally {
    active = false;
    cleanup();
  }
  return true;
}
