// dsh-tui's Divider, reduced to the one use the trajectory scene makes: a
// rule of an explicit `width`. The original measures the box after layout to
// fit nested containers; the scene always passes the width.
import { jsx as _jsx } from "react/jsx-runtime";
import { Box, Text, useTerminalSize } from '../../ui.js';

export function Divider({ width, color, char = '─', padding = 0 }) {
    const { columns } = useTerminalSize();
    const lineWidth = Math.max(0, (width ?? columns) - padding);
    return (_jsx(Box, { ...(width !== undefined ? { width } : {}), children: _jsx(Text, { dimColor: !color, color: color, wrap: "truncate-end", children: char.repeat(lineWidth) }) }));
}