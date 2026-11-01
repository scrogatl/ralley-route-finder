// Click a heading of a table.sortable to sort by that column; click again to reverse.
// A cell's data-sort value, if any, is used in place of its text. Number columns
// (th.num) sort highest first on the first click, text columns A to Z.
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
  const sort = (th, col) => {
    const numeric = th.classList.contains('num');
    const current = th.getAttribute('aria-sort');
    const descending = current ? current === 'ascending' : numeric;
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
  };
  heads.forEach((th, col) => {
    th.tabIndex = 0;
    th.title = 'Sort by this column';
    th.addEventListener('click', () => sort(th, col));
    th.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(th, col); }
    });
  });
});
