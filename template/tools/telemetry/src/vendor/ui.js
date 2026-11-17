// Shim for dsh-tui's ui.js over npm ink. The vendored views name colours by
// theme key ('subtle', 'error'); Text/Box translate them to the fixed palette.
// dsh-tui's ink fork also has mouse props (onClick, onMouseEnter, onWheel...):
// npm ink has no mouse, so they are dropped here and the keyboard does it all.
import React from 'react';
import { Box as InkBox, Text as InkText, useInput, useWindowSize } from 'ink';
import { resolveColor } from './theme.js';

const MOUSE_PROPS = ['onClick', 'onMouseEnter', 'onMouseLeave', 'onWheel', 'onMouseDown', 'onMouseUp'];

function withoutMouse(props) {
    const out = { ...props };
    for (const name of MOUSE_PROPS)
        delete out[name];
    return out;
}

export const Box = React.forwardRef(function Box(props, ref) {
    const out = withoutMouse(props);
    for (const key of ['backgroundColor', 'borderColor'])
        if (out[key] !== undefined)
            out[key] = resolveColor(out[key]);
    return React.createElement(InkBox, { ...out, ref });
});

export function Text(props) {
    const out = withoutMouse(props);
    if (out.color !== undefined)
        out.color = resolveColor(out.color);
    if (out.backgroundColor !== undefined)
        out.backgroundColor = resolveColor(out.backgroundColor);
    return React.createElement(InkText, out);
}

export function NoSelect({ children }) {
    return children;
}

export { useInput };

/** dsh-tui's useTerminalSize: { columns, rows } that follows resizes. */
export function useTerminalSize() {
    return useWindowSize();
}

/** One fixed theme: the name is ignored by getTheme(). */
export function useTheme() {
    return ['dark', () => { }];
}