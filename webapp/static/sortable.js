// Click a heading of a table.sortable to sort by that column; click again to reverse.
// A cell's data-sort value, if any, is used in place of its text. Number columns
// (th.num) sort highest first on the first click, text columns A to Z. A table
// with data-remember="name" keeps its sort in this browser between visits.
document.querySelectorAll('table.sortable').forEach(table => {
  const heads = [...table.tHead.rows[0].cells];
  const value = (row, col) => {
    const cell = row.cells[col];
    return cell.dataset.sort ?? cell.textContent.trim();
  };
  const number = text => {
    const n = parseFloat(String(text).replace(/,/g, ''));
    return Number.isNaN(n) ? null : n;
  };
  const key = table.dataset.remember && `sort:${table.dataset.remember}`;
  const sort = (th, col, descending) => {
    const numeric = th.classList.contains('num');
    if (descending === undefined) {
      const current = th.getAttribute('aria-sort');
      descending = current ? current === 'ascending' : numeric;
    }
    const rows = [...table.tBodies[0].rows];
    rows.sort((a, b) => {
      let x = value(a, col), y = value(b, col);
      if (numeric) {
        x = number(x); y = number(y);
        if (x === null || y === null) return (x === null) - (y === null);  // blanks last
        return descending ? y - x : x - y;
      }
      const order = x.localeCompare(y, undefined, {numeric: true, sensitivity: 'base'});
      return descending ? -order : order;
    });
    table.tBodies[0].append(...rows);
    heads.forEach(h => h.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
    if (key) {
      // Storage can be blocked, e.g. in a private window; the sort still works
      try { localStorage.setItem(key, JSON.stringify({heading: th.textContent.trim(), descending})); } catch (e) {}
    }
  };
  heads.forEach((th, col) => {
    th.tabIndex = 0;
    th.title = 'Sort by this column';
    th.addEventListener('click', () => sort(th, col));
    th.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(th, col); }
    });
  });
  if (key) {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(key)); } catch (e) {}
    // Found by heading, so adding a column doesn't move the sort to another one
    const col = saved ? heads.findIndex(h => h.textContent.trim() === saved.heading) : -1;
    if (col >= 0) sort(heads[col], col, !!saved.descending);
  }
});
