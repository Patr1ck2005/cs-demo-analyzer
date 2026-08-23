// Vanilla table sort: click a .sortable th to sort rows by that column.
// Numeric-aware (strips non-numeric suffixes); toggles asc/desc.
(function () {
  function cellValue(tr, idx) {
    const text = tr.children[idx].textContent.trim();
    const num = parseFloat(text.replace(/[^0-9.\-]/g, ''));
    return Number.isFinite(num) ? num : text.toLowerCase();
  }

  function sortTable(table, th) {
    const tbody = table.querySelector('tbody');
    if (!tbody) return;
    const idx = [...th.parentElement.children].indexOf(th);
    const asc = !th.classList.contains('sorted') || th.classList.contains('desc');
    [...table.querySelectorAll('th.sortable')].forEach((el) => {
      el.classList.remove('sorted', 'asc', 'desc');
    });
    th.classList.add('sorted', asc ? 'asc' : 'desc');
    const rows = [...tbody.querySelectorAll('tr')];
    rows.sort((a, b) => {
      const va = cellValue(a, idx), vb = cellValue(b, idx);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return asc ? cmp : -cmp;
    });
    rows.forEach((r) => tbody.appendChild(r));
  }

  document.addEventListener('click', (e) => {
    const th = e.target.closest('th.sortable');
    if (!th) return;
    sortTable(th.closest('table'), th);
  });
})();
