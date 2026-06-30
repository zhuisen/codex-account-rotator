export const THEMES = {
  dark: {
    appBg:"#0e1117", deskBg:"radial-gradient(130% 120% at 50% -10%, #151c26 0%, #080a0e 65%)",
    chromeBg:"#0c1015", chromeBorder:"rgba(255,255,255,.07)", titleText:"#cfd6df",
    railBg:"#0a0e12", railBorder:"rgba(255,255,255,.06)",
    text:"#eef2f7", text2:"#aab3c0", muted:"#6b7480", email:"#8b95a1", faint:"#454d57",
    heroBg:"#131c20", heroBorder:"rgba(45,212,191,.25)", heroShadow:"none",
    cardBg:"#141a22", cardBorder:"rgba(255,255,255,.06)", curCardBg:"rgba(45,212,191,.07)",
    cardHoverShadow:"0 10px 26px rgba(0,0,0,.4)",
    divider:"rgba(255,255,255,.08)",
    accent:"#2dd4bf", accentText:"#06231f", accentTextSoft:"#9fe9df",
    accentSoft:"rgba(45,212,191,.10)", accentBorder:"rgba(45,212,191,.34)",
    ringTrack:"rgba(255,255,255,.09)", barTrack:"rgba(255,255,255,.09)",
    ghostBorder:"rgba(255,255,255,.12)", ghostText:"#aab3c0", ghostBg:"rgba(255,255,255,.02)",
    shadow:"0 28px 64px rgba(0,0,0,.5)",
    toastBg:"rgba(20,26,34,.94)", toastText:"#eef2f7", toastBorder:"rgba(45,212,191,.3)",
    sunBg:"transparent", sunColor:"#6b7480", moonBg:"#2dd4bf", moonColor:"#06231f",
  },
  light: {
    appBg:"#eef1f5", deskBg:"radial-gradient(130% 120% at 50% -10%, #f4f7fb 0%, #dbe1e9 100%)",
    chromeBg:"#f7f9fb", chromeBorder:"rgba(0,0,0,.1)", titleText:"#39414b",
    railBg:"#e7ebf0", railBorder:"rgba(0,0,0,.06)",
    text:"#161b22", text2:"#4d5663", muted:"#8a93a0", email:"#6b7682", faint:"#aab2bd",
    heroBg:"#ffffff", heroBorder:"rgba(14,159,142,.3)", heroShadow:"0 1px 3px rgba(0,0,0,.05)",
    cardBg:"#ffffff", cardBorder:"rgba(0,0,0,.07)", curCardBg:"rgba(14,159,142,.05)",
    cardHoverShadow:"0 10px 26px rgba(0,0,0,.12)",
    divider:"rgba(0,0,0,.1)",
    accent:"#0e9f8e", accentText:"#ffffff", accentTextSoft:"#0c8576",
    accentSoft:"rgba(14,159,142,.09)", accentBorder:"rgba(14,159,142,.4)",
    ringTrack:"rgba(0,0,0,.09)", barTrack:"rgba(0,0,0,.08)",
    ghostBorder:"rgba(0,0,0,.12)", ghostText:"#4d5663", ghostBg:"#ffffff",
    shadow:"0 28px 64px rgba(0,0,0,.18)",
    toastBg:"rgba(255,255,255,.97)", toastText:"#161b22", toastBorder:"rgba(14,159,142,.35)",
    sunBg:"#0e9f8e", sunColor:"#ffffff", moonBg:"transparent", moonColor:"#8a93a0",
  },
};

export type Theme = typeof THEMES.dark;

export const STATUS_COLORS: Record<string, string> = {
  live: "#27B26B", low: "#E0901C", cool: "#2BA0C0", dead: "#E0524D",
};
export const STATUS_TEXT: Record<string, string> = {
  live: "活", low: "低", cool: "冷却", dead: "死",
};
