// 表格排序与行内导航：只改展示顺序，不改任何数据。
const tableState = { sort: new WeakMap() };

function cellValue(row, index) {
  const cell = row.children[index];
  if (!cell) return "";
  const text = cell.textContent.trim();
  return text;
}

function isNumeric(text) {
  return /^-?\d+(\.\d+)?$/.test(text);
}

function compare(a, b) {
  if (isNumeric(a) && isNumeric(b)) {
    return Number(a) - Number(b);
  }
  return a.localeCompare(b, "zh-Hans-CN");
}

function sortTable(table, index) {
  const body = table.tBodies[0];
  if (!body) return;
  const current = tableState.sort.get(table) || {};
  const direction = current.index === index && current.direction === "asc" ? "desc" : "asc";
  tableState.sort.set(table, { index, direction });
  const rows = Array.from(body.rows);
  rows.sort((left, right) => {
    const result = compare(cellValue(left, index), cellValue(right, index));
    return direction === "asc" ? result : -result;
  });
  rows.forEach((row) => body.appendChild(row));
  table.querySelectorAll("th").forEach((th, thIndex) => {
    th.removeAttribute("aria-sort");
    if (thIndex === index) {
      th.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
    }
  });
}

function openRow(row) {
  const invoice = row.dataset.invoice;
  if (!invoice) return;
  const dialog = document.getElementById("invoice-dialog");
  if (!dialog) return;
  dialog.dataset.pending = invoice;
  dialog.dispatchEvent(new CustomEvent("invoice:open", { detail: { invoice } }));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("table.table").forEach((table) => {
    table.querySelectorAll("thead th").forEach((th, index) => {
      th.addEventListener("click", () => sortTable(table, index));
      th.style.cursor = "pointer";
      th.title = "排序";
    });
  });

  document.querySelectorAll("tr.row-link").forEach((row) => {
    row.addEventListener("click", () => openRow(row));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openRow(row);
      }
    });
  });
});
