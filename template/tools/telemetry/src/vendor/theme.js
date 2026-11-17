// Shim for dsh-tui's theme.js: one fixed palette, the whole `dark` theme of
// dsh-tui 0.14.0 so no key a vendored view names can fall through to ink as
// an unknown colour. No theme switching, by design.
const rgb = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgb(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255})`;
};

export const PALETTE = Object.freeze({
    autoAccept: rgb('#B3A0D4'),
    bashBorder: rgb('#D194AE'),
    accent: rgb('#7DA1DE'),
    toolNameMutate: rgb('#E5C07B'),
    toolNameExec: rgb('#56B6C2'),
    accentShimmer: rgb('#ABC2EC'),
    activity: rgb('#7DA1DE'),
    activityShimmer: rgb('#ABC2EC'),
    permission: rgb('#ABC2EC'),
    permissionShimmer: rgb('#C9D7F2'),
    planMode: rgb('#7FAE99'),
    ide: rgb('#5E88CC'),
    promptBorder: rgb('#55606F'),
    promptBorderShimmer: rgb('#7DA1DE'),
    text: rgb('#E8E6E0'),
    inverseText: rgb('#22262E'),
    inactive: rgb('#8D95A6'),
    inactiveShimmer: rgb('#AAB2C2'),
    subtle: rgb('#5E6673'),
    suggestion: rgb('#ABC2EC'),
    remember: rgb('#ABC2EC'),
    background: rgb('#5E88CC'),
    success: rgb('#82B89D'),
    error: rgb('#DA8A93'),
    warning: rgb('#D8B270'),
    merged: rgb('#B3A0D4'),
    warningShimmer: rgb('#E4C78E'),
    diffAdded: rgb('#27392C'),
    diffRemoved: rgb('#3E2A2C'),
    diffAddedDimmed: rgb('#2B352C'),
    diffRemovedDimmed: rgb('#362B2C'),
    diffAddedWord: rgb('#57956B'),
    diffRemovedWord: rgb('#B26671'),
    toolCardBackground: rgb('#242B3A'),
    toolCardBackgroundDim: rgb('#1C2330'),
    toolDotExec: rgb('#7FAE99'),
    toolDotRead: rgb('#82B8C7'),
    toolDotWrite: rgb('#B3A0D4'),
    toolDotWeb: rgb('#7DA1DE'),
    toolDotTask: rgb('#D194AE'),
    professionalBlue: rgb('#7DA1DE'),
    chromeYellow: rgb('#D8B270'),
    contextBarSystem: rgb('#22305F'),
    contextBarPrompt: rgb('#2B3D78'),
    contextBarAssistant: rgb('#344A92'),
    contextBarThinking: rgb('#4D6BFE'),
    contextBarTools: rgb('#5A7CFF'),
    ignition: rgb('#82B9FF'),
    ignitionDim: rgb('#1B1E28'),
    // '' = no fill, as in dsh-tui (ink treats an empty colour as unset).
    userMessageBackground: '',
    userMessageBackgroundHover: rgb('#3B5BDB'),
    messageActionsBackground: rgb('#2E333D'),
    selectionBg: rgb('#3B4A66'),
    bashMessageBackgroundColor: rgb('#2C3038'),
    memoryBackgroundColor: rgb('#30353D'),
    fastMode: rgb('#E09A58'),
    userPromptLabel: rgb('#FFDF80'),
    subagentBullet: rgb('#D194AE'),
});

export function getTheme() {
    return PALETTE;
}

/** A theme key becomes its colour; anything else (rgb(), hex, ansi names) passes through. */
export function resolveColor(color) {
    return typeof color === 'string' && Object.hasOwn(PALETTE, color) ? PALETTE[color] : color;
}