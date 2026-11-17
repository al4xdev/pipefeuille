// Copied from dsh-tui 0.14.0: a hint string with **bold** key segments.
import { Fragment as _Fragment, jsx as _jsx } from "react/jsx-runtime";
import { Text } from '../../ui.js';

export function HintLine({ text }) {
    const parts = text.split('**');
    if (parts.length < 3)
        return _jsx(_Fragment, { children: text });
    return (_jsx(_Fragment, { children: parts.map((part, index) => index % 2 === 1 ? _jsx(Text, { bold: true, children: part }, index) : part) }));
}