// Shim for dsh-tui's i18n.js: English only, the trajectory keys copied from
// dsh-tui 0.14.0. `{{name}}` placeholders as in the original.
const EN = {
    'trajectory-unsupported': 'This kernel provides no trajectory data; there is no session timeline to show.',
    'trajectory-unsupported-exit': 'q / Esc to return',
    'trajectory-time-observed': 'time is when the event was received',
    'trajectory-wait-elapsed': 'waiting {{duration}}',
    'trajectory-inspect-unavailable': 'source event no longer readable (likely compacted)',
    'trajectory-view-agent': 'agent {{label}}',
    'trajectory-view-parent': 'parent turn {{turn}}',
    'trajectory-view-descendants': 'descendants {{label}}',
    'trajectory-drill-hint': 'a focus this agent',
    'trajectory-scope-hint': 'a cycle scope · Esc back to session',
    'trajectory-backend-label': 'trajectory source: {{name}}',
    'trajectory-backend-dsh': 'DSH session log',
    'traj-title': 'Trajectory',
    'traj-totals': '{{turns}} turns · {{steps}} rows',
    'traj-errors': '{{n}} failed',
    'traj-retries': '{{n}} retries',
    'traj-matches': '{{n}}/{{total}} matched',
    'traj-tab-timeline': 'Timeline',
    'traj-tab-hotspot': 'Hotspot',
    'traj-hot-tools': 'Tools',
    'traj-hot-model': 'Model',
    'traj-hot-turns': 'Turns',
    'traj-sort-duration': 'by duration',
    'traj-sort-count': 'by count',
    'traj-sort-tokens': 'by tokens',
    'traj-proj-sequence': 'even',
    'traj-proj-time': 'wall-clock',
    'traj-proj-compressed': 'compressed',
    'traj-hint-timeline': '**↑/↓** move · **←/→** view · **[ ]** failures · **{ }** turns · **/** query · **m** projection · **enter** detail · **q** back',
    'traj-hint-hotspot': '**↑/↓** move · **←/→** view · **t** sort · **enter** locate in timeline · **q** back',
    'traj-hint-query': '**tool:** **kind:** **turn:** **err:** **run:** **>10s** **tok>1k** · bare word = full text · **enter** apply · **esc** clear',
    'traj-hint-expanded': '**j/k** page · **enter/esc** collapse · **q** back',
};

export function t(key, params = {}) {
    const text = EN[key] ?? key;
    return text.replace(/\{\{(\w+)\}\}/g, (_, name) => String(params[name] ?? ''));
}