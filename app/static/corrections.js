// 更正补入：只发请求与展示结果，全部判定与事务在服务端。
const correctionState = { busy: false };

function correctionToast(text, tone) {
  const node = document.getElementById("correction-toast");
  if (!node) return;
  node.textContent = text;
  node.className = tone === "error" ? "notice" : "toast";
}

async function publishCorrection(mode) {
  if (correctionState.busy) return;
  const file = document.getElementById("correction-file")?.value.trim() || "";
  correctionState.busy = true;
  correctionToast(mode === "replace" ? "提交整批替换（预期被拒绝）…" : "补入发布中…", "muted");
  try {
    const response = await fetch("/api/corrections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, mode }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      correctionToast(`已拒绝：${data.message || response.status}`, "error");
    } else {
      const label = data.reused ? "幂等复用" : "发布成功";
      const ledgers = (data.ledgers || []).map((row) => `${row.label}:${row.status}`).join(" ");
      correctionToast(`${label} ${data.run_id} · 账单 ${data.totals?.invoices ?? 0} 张 · ${ledgers}`,
        "muted");
      setTimeout(() => window.location.assign(
        `/corrections?run_id=${encodeURIComponent(data.run_id)}`), 900);
    }
  } catch (error) {
    correctionToast(error.message, "error");
  } finally {
    correctionState.busy = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("run-correction")
    ?.addEventListener("click", () => publishCorrection("patch"));
  document.getElementById("run-correction-replace")
    ?.addEventListener("click", () => publishCorrection("replace"));
  document.getElementById("correction-file")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      publishCorrection("patch");
    }
  });
});
