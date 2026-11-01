import { colorSchemeDark, themeQuartz } from "ag-grid-community";

export const crucibleGridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
  accentColor: "#a6ffcb",
  backgroundColor: "#0b1514",
  foregroundColor: "#dce7e5",
  chromeBackgroundColor: "#0f1c19",
  borderColor: "rgba(255,255,255,0.09)",
  headerTextColor: "#8da19d",
  oddRowBackgroundColor: "rgba(255,255,255,0.018)",
  selectedRowBackgroundColor: "rgba(166,255,203,0.08)",
  fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
  fontSize: 12,
  spacing: 6,
});
