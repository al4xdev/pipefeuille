// Shim for dsh-tui's useAnimationFrame: [ref, msSinceMount], advancing every
// `intervalMs`. The fork pauses when the box is offscreen; the scene is the
// whole screen here, so a plain interval is the same thing.
import React from 'react';

export function useAnimationFrame(intervalMs) {
    const ref = React.useRef(null);
    const [start] = React.useState(() => Date.now());
    const [time, setTime] = React.useState(0);
    React.useEffect(() => {
        const timer = setInterval(() => setTime(Date.now() - start), intervalMs);
        return () => clearInterval(timer);
    }, [intervalMs, start]);
    return [ref, time];
}