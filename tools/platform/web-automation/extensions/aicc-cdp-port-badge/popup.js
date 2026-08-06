const model = globalThis.AiccCdpBadge;
const current = document.querySelector("#current");
const buttons = [...document.querySelectorAll("button[data-slot]")];

function render(slot) {
  const display = model.slots[slot] ?? model.unconfigured;
  current.textContent = `Current: ${display.label}`;
  for (const button of buttons) button.setAttribute("aria-pressed", String(button.dataset.slot === slot));
}

async function load() {
  const stored = await chrome.storage.local.get(model.storageKey);
  render(String(stored[model.storageKey] ?? ""));
}

for (const button of buttons) {
  button.addEventListener("click", async () => {
    const slot = button.dataset.slot;
    await chrome.storage.local.set({ [model.storageKey]: slot });
    render(slot);
  });
}
void load();
