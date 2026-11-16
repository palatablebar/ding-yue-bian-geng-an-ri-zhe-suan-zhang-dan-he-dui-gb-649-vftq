// 账单明细：点行取 /api/invoices/<账单号>，在 dialog 里列出分段与抵扣行。
const invoiceState = { cache: new Map(), loading: false };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function buildTable(headers, rows) {
  const table = el("table", "table");
  const thead = el("thead");
  const headRow = el("tr");
  headers.forEach(([label, numeric]) => {
    const th = el("th", numeric ? "num" : "", label);
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  const tbody = el("tbody");
  rows.forEach((cells) => {
    const tr = el("tr");
    cells.forEach(([value, numeric]) => {
      const td = el("td", numeric ? "num" : "", value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
  const wrap = el("div", "table-wrap");
  wrap.appendChild(table);
  return wrap;
}

function renderInvoice(body, data) {
  body.replaceChildren();
  const invoice = data.invoice;
  const head = el("div", "block-head");
  head.appendChild(el("h3", "", "分段"));
  head.appendChild(el("span", "sub",
    `${invoice.period_days} 天 · ${invoice.amount} 元 · 分段 ${data.segments.length} · 抵扣行 ${data.components.length}`));
  body.appendChild(head);

  body.appendChild(buildTable(
    [["起", false], ["止", false], ["天数", true], ["套餐", false], ["状态", false],
     ["月价(元)", true], ["金额(元)", true]],
    data.segments.map((row) => [
      [row.start_date, false], [row.end_date, false], [row.days, true],
      [row.plan, false], [row.state_label || row.state, false],
      [row.monthly, true], [row.amount, true],
    ]),
  ));

  body.appendChild(el("h3", "", "抵扣行"));
  body.appendChild(buildTable(
    [["类型", false], ["来源", false], ["天数", true], ["金额(元)", true]],
    data.components.map((row) => [
      [row.kind === "charge" ? "补收" : "抵扣", false], [row.label, false],
      [row.days, true], [row.amount, true],
    ]),
  ));
}

async function loadInvoice(invoiceId) {
  if (invoiceState.loading) return;
  const dialog = document.getElementById("invoice-dialog");
  const body = document.getElementById("invoice-body");
  const title = document.getElementById("invoice-title");
  if (!dialog || !body || !title) return;
  invoiceState.loading = true;
  title.textContent = invoiceId;
  body.replaceChildren(el("p", "empty", "读取中…"));
  try {
    let data = invoiceState.cache.get(invoiceId);
    if (!data) {
      const response = await fetch(`/api/invoices/${encodeURIComponent(invoiceId)}`,
        { headers: { Accept: "application/json" } });
      data = await response.json();
      if (!response.ok) throw new Error(data.message || `请求失败 ${response.status}`);
      invoiceState.cache.set(invoiceId, data);
    }
    renderInvoice(body, data);
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
  } catch (error) {
    body.replaceChildren(el("p", "notice", error.message));
  } finally {
    invoiceState.loading = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.getElementById("invoice-dialog");
  if (!dialog) return;
  dialog.addEventListener("invoice:open", (event) => loadInvoice(event.detail.invoice));
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") dialog.close();
  });
});
