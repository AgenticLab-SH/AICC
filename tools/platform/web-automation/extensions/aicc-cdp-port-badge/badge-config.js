(() => {
  const slots = Object.freeze({
    "9222": Object.freeze({ badge: "22", color: "#2563EB", label: "CDP Chrome 9222" }),
    "9223": Object.freeze({ badge: "23", color: "#EA580C", label: "CDP Chrome 9223" }),
    "9335": Object.freeze({ badge: "35", color: "#0F766E", label: "CDP Whale 9335" })
  });

  globalThis.AiccCdpBadge = Object.freeze({
    storageKey: "slot",
    slots,
    unconfigured: Object.freeze({ badge: "?", color: "#5F6368", label: "CDP port not configured" })
  });
})();
