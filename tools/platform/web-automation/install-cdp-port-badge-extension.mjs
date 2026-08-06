#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";

const allowedSlots = new Set(["9222", "9223", "9335"]);

function parseArguments(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--") || index + 1 >= argv.length) {
      throw new Error(`Invalid argument near: ${key}`);
    }
    result[key.slice(2)] = argv[index + 1];
    index += 1;
  }
  return result;
}

class CdpConnection {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.socket = null;
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) {
        pending.reject(new Error(`${pending.method}: ${message.error.message}`));
      } else {
        pending.resolve(message.result ?? {});
      }
    });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Timed out connecting to the CDP browser endpoint.")), 8000);
      this.socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("Failed to connect to the CDP browser endpoint."));
      }, { once: true });
    });
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method}: timed out`));
      }, 10000);
      this.pending.set(id, { resolve, reject, timer, method });
      const message = { id, method, params };
      if (sessionId) message.sessionId = sessionId;
      this.socket.send(JSON.stringify(message));
    });
  }

  close() {
    this.socket?.close();
  }
}

async function readManifest(extensionPath) {
  const manifestPath = path.join(extensionPath, "manifest.json");
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  if (manifest.manifest_version !== 3 || manifest.name !== "AICC CDP Port Badge") {
    throw new Error(`Unexpected extension manifest: ${manifestPath}`);
  }
  const permissions = manifest.permissions ?? [];
  if (permissions.length !== 1 || permissions[0] !== "storage") {
    throw new Error("The identity extension must have only the storage permission.");
  }
  if (manifest.host_permissions || manifest.content_scripts || manifest.optional_host_permissions) {
    throw new Error("The identity extension must not contain host permissions or content scripts.");
  }
  return manifest;
}

async function pinExtension(connection, sessionId, extensionId) {
  const expression = `(async () => {
    await chrome.developerPrivate.updateExtensionConfiguration({
      extensionId: ${JSON.stringify(extensionId)},
      pinnedToToolbar: true
    });
    const info = await chrome.developerPrivate.getExtensionInfo(${JSON.stringify(extensionId)});
    return { pinned: info.pinnedToToolbar === true };
  })()`;
  const evaluated = await connection.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  }, sessionId);
  if (evaluated.exceptionDetails || evaluated.result?.subtype === "error" || evaluated.result?.value?.pinned !== true) {
    const detail = evaluated.exceptionDetails?.exception?.description
      ?? evaluated.exceptionDetails?.text
      ?? evaluated.result?.description
      ?? "unknown browser UI error";
    throw new Error(`Browser extensions UI rejected the toolbar pin request: ${detail}`);
  }
}

async function configureExtensionStorage(connection, extensionId, slot) {
  const target = await connection.send("Target.createTarget", {
    url: `chrome-extension://${extensionId}/popup.html`,
    background: true
  });
  try {
    const attached = await connection.send("Target.attachToTarget", {
      targetId: target.targetId,
      flatten: true
    });
    await connection.send("Runtime.enable", {}, attached.sessionId);
    const expression = `(async () => {
      await chrome.storage.local.set({ slot: ${JSON.stringify(slot)} });
      await new Promise((resolve) => setTimeout(resolve, 150));
      const stored = await chrome.storage.local.get("slot");
      return {
        slot: stored.slot,
        badge: await chrome.action.getBadgeText({}),
        title: await chrome.action.getTitle({})
      };
    })()`;
    const evaluated = await connection.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true
    }, attached.sessionId);
    const expectedBadge = slot.slice(-2);
    if (evaluated.exceptionDetails
      || String(evaluated.result?.value?.slot ?? "") !== slot
      || String(evaluated.result?.value?.badge ?? "") !== expectedBadge) {
      throw new Error("The extension rejected its profile-local slot setting.");
    }
    return evaluated.result.value;
  } finally {
    await connection.send("Target.closeTarget", { targetId: target.targetId }).catch(() => {});
  }
}

async function findLoadedExtension(connection) {
  const target = await connection.send("Target.createTarget", {
    url: "chrome://extensions/",
    background: true
  });
  try {
    const attached = await connection.send("Target.attachToTarget", {
      targetId: target.targetId,
      flatten: true
    });
    await connection.send("Runtime.enable", {}, attached.sessionId);
    const expression = `(async () => {
      for (let attempt = 0; attempt < 40; attempt += 1) {
        if (chrome?.developerPrivate?.getExtensionsInfo) {
          const items = await chrome.developerPrivate.getExtensionsInfo({
            includeDisabled: true,
            includeTerminated: true
          });
          return items
            .filter((item) => item.name === "AICC CDP Port Badge")
            .map((item) => ({
              id: item.id,
              name: item.name,
              path: item.path ?? "",
              enabled: item.state === "ENABLED",
              pinned: item.pinnedToToolbar === true
            }));
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      throw new Error("chrome.developerPrivate did not become available");
    })()`;
    const evaluated = await connection.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true
    }, attached.sessionId);
    if (evaluated.exceptionDetails || !Array.isArray(evaluated.result?.value)) {
      return [];
    }
    return evaluated.result.value;
  } finally {
    await connection.send("Target.closeTarget", { targetId: target.targetId }).catch(() => {});
  }
}

async function loadUnpacked(connection, extensionPath) {
  const parameters = { path: extensionPath, enableInIncognito: false };
  try {
    return await connection.send("Extensions.loadUnpacked", parameters);
  } catch (error) {
    if (!String(error.message).includes("Method not available")) throw error;
    let sessionError = error;
    try {
      const target = await connection.send("Target.createTarget", {
        url: "chrome://extensions/",
        background: true
      });
      try {
        const attached = await connection.send("Target.attachToTarget", {
          targetId: target.targetId,
          flatten: true
        });
        await connection.send("Runtime.enable", {}, attached.sessionId);
        return await connection.send("Extensions.loadUnpacked", parameters, attached.sessionId);
      } finally {
        await connection.send("Target.closeTarget", { targetId: target.targetId }).catch(() => {});
      }
    } catch (errorFromSession) {
      sessionError = errorFromSession;
    }
    const existing = await findLoadedExtension(connection);
    if (existing.length === 1) return { id: existing[0].id };
    throw sessionError;
  }
}

async function main() {
  const args = parseArguments(process.argv.slice(2));
  const endpoint = new URL(args.endpoint);
  const slot = String(args.slot ?? "");
  const extensionPath = path.resolve(args.extension ?? "");
  if (!allowedSlots.has(slot)) throw new Error(`Unsupported CDP slot: ${slot}`);
  await readManifest(extensionPath);

  const versionResponse = await fetch(new URL("/json/version", endpoint));
  if (!versionResponse.ok) throw new Error(`CDP endpoint returned HTTP ${versionResponse.status}`);
  const version = await versionResponse.json();
  if (!version.webSocketDebuggerUrl) throw new Error("CDP endpoint did not expose a browser WebSocket URL.");

  const connection = new CdpConnection(version.webSocketDebuggerUrl);
  await connection.connect();
  let configurationTargetId;
  try {
    const loaded = await loadUnpacked(connection, extensionPath);
    const extensionId = loaded.id;
    if (!extensionId) throw new Error("Extensions.loadUnpacked did not return an extension ID.");

    const display = await configureExtensionStorage(connection, extensionId, slot);

    const configurationTarget = await connection.send("Target.createTarget", {
      url: "chrome://extensions/",
      background: true
    });
    configurationTargetId = configurationTarget.targetId;
    const attached = await connection.send("Target.attachToTarget", {
      targetId: configurationTarget.targetId,
      flatten: true
    });
    await connection.send("Runtime.enable", {}, attached.sessionId);

    await pinExtension(connection, attached.sessionId, extensionId);

    let match;
    try {
      const installed = await connection.send("Extensions.getExtensions");
      match = installed.extensions?.find((extension) => extension.id === extensionId);
    } catch (error) {
      if (!String(error.message).includes("Method not available")) throw error;
      match = (await findLoadedExtension(connection)).find((extension) => extension.id === extensionId);
    }
    if (!match?.enabled) {
      throw new Error("Extension installation or profile-local slot verification failed.");
    }

    process.stdout.write(`${JSON.stringify({
      ok: true,
      endpoint: endpoint.origin,
      slot,
      extension_id: extensionId,
      extension_path: match.path,
      enabled: match.enabled,
      toolbar_pinned: true,
      badge: display.badge,
      title: display.title
    })}\n`);
  } finally {
    if (configurationTargetId) {
      await connection.send("Target.closeTarget", { targetId: configurationTargetId }).catch(() => {});
    }
    connection.close();
  }
}

main().catch((error) => {
  const args = (() => {
    try { return parseArguments(process.argv.slice(2)); } catch { return {}; }
  })();
  if (String(args.slot ?? "") === "9335" && String(error.message).includes("Extensions.loadUnpacked: Method not available")) {
    process.stdout.write(`${JSON.stringify({
      ok: true,
      status: "unsupported",
      reason: "whale_extensions_load_unpacked_unavailable",
      endpoint: args.endpoint ?? "",
      slot: "9335",
      extension_id: "",
      extension_path: "",
      enabled: false,
      toolbar_pinned: false,
      badge: "",
      title: ""
    })}\n`);
    return;
  }
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
