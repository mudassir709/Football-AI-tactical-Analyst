// Turns a team's measured kit colour (e.g. "#C7C9AA") into a plain name
// ("white") for the AI coaching report. The colour is measured from the
// video, so stadium light and shadows make it paler or greyer than the real
// kit; the rules below are written with that in mind.

/** Hex colour -> hue (0-360), saturation and lightness (0-1), plus chroma (0-255). */
function toHsl(hex: string) {
  const n = parseInt(hex.replace("#", ""), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const chroma = max - min;
  const lightness = (max + min) / 2 / 255;
  const saturation = chroma === 0 ? 0 : chroma / 255 / (1 - Math.abs(2 * lightness - 1));
  let hue = 0;
  if (chroma > 0) {
    if (max === r) hue = ((g - b) / chroma) % 6;
    else if (max === g) hue = (b - r) / chroma + 2;
    else hue = (r - g) / chroma + 4;
    hue = (hue * 60 + 360) % 360;
  }
  return { hue, saturation, lightness, chroma };
}

/** A plain colour name for a kit, e.g. "white", "dark grey", "navy", "red". */
export function colourName(hex: string): string {
  const { hue, saturation, lightness, chroma } = toHsl(hex);

  // Very light and not very colourful: a white kit (often looks cream or
  // bluish-white on video).
  if ((lightness > 0.65 && saturation < 0.3) || (lightness > 0.8 && saturation < 0.45)) return "white";

  // Hardly any colour: black or a shade of grey. Dark blue counts as colour
  // much sooner, because navy kits are common and look grey on video.
  const isBlue = hue >= 190 && hue < 260;
  if (chroma < (isBlue ? 8 : 20)) {
    if (lightness < 0.2) return "black";
    if (lightness < 0.45) return "dark grey";
    return lightness < 0.65 ? "grey" : "light grey";
  }

  // A colour: name it by its hue, then say if it is light or dark.
  const dark = lightness < 0.4;
  const light = lightness > 0.7;
  if (hue < 20 || hue >= 340) return dark ? "dark red" : light ? "pink" : "red";
  if (hue < 45) return dark ? "brown" : "orange";
  if (hue < 70) return dark ? "olive" : "yellow";
  if (hue < 160) return dark ? "dark green" : light ? "light green" : "green";
  if (hue < 190) return dark ? "dark teal" : "teal";
  if (hue < 260) return dark ? "navy" : light ? "sky blue" : "blue";
  if (hue < 300) return dark ? "dark purple" : "purple";
  return light ? "pink" : "magenta";
}
