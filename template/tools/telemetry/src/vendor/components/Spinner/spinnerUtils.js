// The two colour helpers the trajectory motion uses, copied from dsh-tui
// 0.14.0 components/Spinner/spinnerUtils.js.
export function interpolateColor(color1, color2, t) {
    const blend = (from, to) => Math.round(from + (to - from) * t);
    return {
        r: blend(color1.r, color2.r),
        g: blend(color1.g, color2.g),
        b: blend(color1.b, color2.b),
    };
}
const RGB_STRING_PATTERN = /rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/;
const rgbParseCache = new Map();
export function parseRGB(colorStr) {
    const remembered = rgbParseCache.get(colorStr);
    if (remembered !== undefined)
        return remembered;
    const parts = colorStr.match(RGB_STRING_PATTERN);
    const parsed = parts
        ? {
            r: parseInt(parts[1], 10),
            g: parseInt(parts[2], 10),
            b: parseInt(parts[3], 10),
        }
        : null;
    rgbParseCache.set(colorStr, parsed);
    return parsed;
}