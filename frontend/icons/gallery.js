// Icon Gallery — a dev view of the whole icon registry, in a grid, with names.
//
// It exists because a style outlier is invisible in a menu and obvious here: a wrong stroke weight,
// a filled shape among stroked ones, a mark that overflows the 16px box, or a hardcoded colour that
// looks fine in light and disappears in dark. Open it (Window > Icon Gallery, or the #icons hash),
// flip the theme switch, and scan the columns.
//
// The "Show descriptions" toggle turns it into a content-review page as well: with it on, each tile
// carries the description and Needs line that the hover card would show, which is the only practical
// way to read 239 of them for tone in one pass. It walks the live menu configs for that text, so a
// description added to a config appears here without anything being registered twice.
//
// The three checks along the top are the ones a human eye is bad at, so they are computed:
//   - how many icons are registered, and how many menu leaves there are to cover
//   - whether any icon hardcodes a colour instead of inheriting currentColor
//   - whether every icon declares the shared geometry (16×16 viewBox, stroke-width 1.5)
// Anything they flag is listed by name underneath rather than merely counted.

import * as wm from '../windowManager.js';
import { h } from '../resultView.js';
import { ICON_GROUPS, ICONS } from './registry.js';
import * as brand from '../brand/brand.js';

const WINDOW_ID = 'icon-gallery';

// A colour literal anywhere in an icon body is a bug: it will be wrong in one of the two themes.
// currentColor and the fill-opacity shading are the only things allowed to touch colour.
const HARDCODED_COLOR = /(#[0-9a-f]{3,8}\b)|(\brgba?\()|(\bhsla?\()|(var\(--)|((?:fill|stroke)="(?!none|currentColor)[a-z]+")/i;

function auditIcon(markup) {
  const problems = [];
  if (HARDCODED_COLOR.test(markup)) problems.push('hardcoded colour');
  if (!markup.includes('viewBox="0 0 16 16"')) problems.push('not a 16×16 viewBox');
  if (!markup.includes('stroke-width="1.5"')) problems.push('root stroke-width is not 1.5');
  if (!markup.includes('stroke="currentColor"')) problems.push('root does not stroke with currentColor');
  return problems;
}

/**
 * Every rendered menu item that uses each icon, with the help text it shows. Read off the live menu
 * bar rather than by importing the configs: the join is exact because menu.js stamps the registry
 * name onto the slot, and whatever the menu actually renders is what gets reviewed. An icon shared
 * between flyouts (Predict, or a distribution) legitimately returns several entries.
 */
function usageByIcon() {
  const map = new Map();
  for (const item of document.querySelectorAll('#menubar .menu-item')) {
    const slot = item.querySelector(':scope > .mi-icon');
    const name = slot && slot.dataset.icon;
    if (!name) continue;
    const entry = {
      label: item.querySelector('.mi-label')?.textContent || '',
      description: item.dataset.help || '',
      needs: item.dataset.needs || '',
    };
    if (!entry.description && !entry.needs) continue;
    const list = map.get(name) || [];
    // Collapse on the TEXT, not the label: File > Recent renders one item per remembered file, all
    // with the same description, and an icon shared between flyouts usually shares its text too.
    // Reviewing the same paragraph five times is noise; the count is the useful part.
    const same = list.find((e) => e.description === entry.description && e.needs === entry.needs);
    if (same) same.also = (same.also || 0) + 1;
    else list.push(entry);
    map.set(name, list);
  }
  return map;
}

function tile(name, markup, problems, usage) {
  const classes = ['icon-tile'];
  if (problems.length) classes.push('icon-tile-flagged');
  if (usage) classes.push('icon-tile-wide');
  const cell = h('div', { class: classes.join(' ') });
  const box = h('span', { class: 'icon-tile-glyph' });
  box.innerHTML = markup;

  if (!usage) {
    cell.append(box, h('code', { class: 'icon-tile-name', text: name }));
  } else {
    const text = h('div', { class: 'icon-tile-text' }, [h('code', { class: 'icon-tile-name', text: name })]);
    if (!usage.length) {
      text.append(h('p', { class: 'icon-tile-unused', text: 'No menu item uses this icon.' }));
    } else {
      for (const use of usage) {
        text.append(h('p', { class: 'icon-tile-item', text: use.also ? `${use.label} (and ${use.also} more with the same text)` : use.label }));
        if (use.description) text.append(h('p', { class: 'icon-tile-desc', text: use.description }));
        if (use.needs) text.append(h('p', { class: 'icon-tile-needs' }, [h('span', { class: 'icon-tile-needs-label', text: 'Needs:' }), ` ${use.needs}`]));
      }
    }
    cell.append(box, text);
  }

  if (problems.length) {
    cell.title = problems.join('; ');
    cell.append(h('span', { class: 'icon-tile-flag', text: problems.join('; ') }));
  }
  return cell;
}

function renderGrids(body, showHelp) {
  body.innerHTML = '';
  const usage = showHelp ? usageByIcon() : null;
  let described = 0;
  let orphans = 0;
  for (const group of ICON_GROUPS) {
    const names = Object.keys(group.icons);
    if (!names.length) continue;
    body.append(h('p', { class: 'section-label', text: `${group.label} — ${names.length}` }));
    const grid = h('div', { class: showHelp ? 'icon-grid icon-grid-help' : 'icon-grid' });
    for (const name of names) {
      const uses = usage ? usage.get(name) || [] : null;
      if (uses) {
        described += uses.filter((u) => u.description).length;
        if (!uses.length) orphans += 1;
      }
      grid.append(tile(name, group.icons[name], auditIcon(group.icons[name]), uses));
    }
    body.append(grid);
  }
  return { described, orphans };
}

/**
 * The brand mark at the sizes that actually matter, in whatever theme the app is in. 16 is the
 * favicon size and the one worth staring at — the mark has to still read as a G there, and the
 * dome has to still read as a curve rather than a smudge.
 */
function buildBrandSection() {
  const wrap = h('div');
  wrap.append(h('p', { class: 'section-label', text: 'Brand mark — brand/mark.svg' }));
  const row = h('div', { class: 'brand-row' });
  const accentRow = h('div', { class: 'brand-row brand-mark-accent' });
  brand.markSource().then((svg) => {
    if (!svg) {
      wrap.append(h('p', { class: 'error', text: 'brand/mark.svg did not load.' }));
      return;
    }
    for (const [host, label] of [
      [row, 'inherits the surrounding ink (light and dark)'],
      [accentRow, 'accent treatment — loading state and About'],
    ]) {
      for (const size of [16, 32, 64, 128]) {
        const cell = h('div', { class: 'brand-cell' });
        const box = h('div');
        box.innerHTML = svg;
        const el = box.querySelector('svg');
        el.setAttribute('width', String(size));
        el.setAttribute('height', String(size));
        cell.append(box, h('code', { class: 'icon-tile-name', text: `${size}px` }));
        host.append(cell);
      }
      host.append(h('p', { class: 'brand-note', text: label }));
    }
  });
  wrap.append(row, accentRow);
  return wrap;
}

function buildContent() {
  const content = h('div', { class: 'icon-gallery' });
  const flagged = [];
  let total = 0;
  for (const group of ICON_GROUPS) {
    for (const name of Object.keys(group.icons)) {
      total += 1;
      const problems = auditIcon(group.icons[name]);
      if (problems.length) flagged.push(`${name}: ${problems.join('; ')}`);
    }
  }
  // A name declared in two groups would be silently shadowed by the later one in ICONS.
  const dupes = total - Object.keys(ICONS).length;

  const body = h('div');
  const status = h('p', { class: 'muted' });
  const toggle = h('input', { type: 'checkbox' });

  const draw = () => {
    const { described, orphans } = renderGrids(body, toggle.checked);
    status.textContent = toggle.checked
      ? `${described} menu item(s) described across ${total} icons${orphans ? `; ${orphans} icon(s) are in the registry but on no menu item` : ''}.`
      : 'Turn on descriptions to review the help text every item shows, alongside its icon.';
  };
  toggle.addEventListener('change', draw);

  content.append(
    h('p', { class: 'muted' }, [
      `${total} icons in ${ICON_GROUPS.length} groups. `,
      'Every one strokes with currentColor, so this grid is also the theme test — switch the theme in the menu bar and nothing here should change except its ink.',
    ]),
    h('p', {
      class: flagged.length || dupes ? 'error' : 'muted',
      text:
        flagged.length || dupes
          ? `${flagged.length} icon(s) break the style rules${dupes ? `, and ${dupes} name(s) are declared in more than one group` : ''} — see the outlined tiles.`
          : 'No style outliers: every icon is a 16×16 viewBox, stroke-width 1.5, currentColor, and no name is declared twice.',
    }),
    h('label', { class: 'checkbox-item' }, [toggle, 'Show descriptions']),
    status,
    buildBrandSection(),
    body,
  );
  draw();
  return content;
}

/** Open (or refocus) the gallery window. */
export function open() {
  if (wm.has(WINDOW_ID)) {
    wm.focus(WINDOW_ID);
    return;
  }
  wm.createWindow({ id: WINDOW_ID, title: 'Icon Gallery', kind: 'result', width: 820, height: 600, content: buildContent() });
}

/** `#icons` in the address bar opens it too, so it is reachable without the menu. */
export function initHashRoute() {
  const check = () => {
    if (window.location.hash === '#icons') open();
  };
  window.addEventListener('hashchange', check);
  check();
}
