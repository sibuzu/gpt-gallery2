"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const token = document.querySelector('meta[name="review-token"]').content;
  let all = [], items = [], category = "全部", index = 0, detail = null;
  let generation = 0, loading = true, deleting = false, zoomed = false;
  let deleteKeyHeld = false;
  let deletedByCategory = {};
  let saves = Promise.resolve();
  const imageCache = new Map(), readyImages = new Set();

  async function api(path, body) {
    const response = await fetch(path, body === undefined ? { cache: "no-store" } : {
      method: "POST", headers: { "Content-Type": "application/json", "X-Review-Token": token },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }

  function notice(text, error = false) {
    $("notice").textContent = text;
    $("notice").classList.toggle("error", error);
  }

  function controls() {
    $("previous").disabled = deleting || index <= 0 || !items.length;
    $("next").disabled = deleting || index >= items.length - 1 || !items.length;
    $("delete").disabled = deleting || loading || !detail || !items.length;
    $("delete").textContent = deleting ? "刪除中…" : "DELETE";
    for (const id of ["category", "dateJump", "pageNumber", "jump", "refresh"]) $(id).disabled = deleting;
    $("zoom").disabled = !items.length;
    $("position").textContent = items.length ? `${index + 1} / ${items.length} 張` : "0 張";
    $("pageNumber").max = Math.max(1, items.length);
    $("pageNumber").value = items.length ? index + 1 : 1;
    const deleted = category === "全部"
      ? Object.values(deletedByCategory).reduce((total, count) => total + count, 0)
      : deletedByCategory[category] || 0;
    $("pageLabel").textContent = `跳到頁碼（全部 ${items.length} 張，已刪 ${deleted} 張）`;
    $("progress").max = Math.max(1, items.length);
    $("progress").value = items.length ? index + 1 : 0;
  }

  function zoom(value) {
    zoomed = value;
    $("stage").classList.toggle("zoomed", value);
    $("zoom").setAttribute("aria-pressed", String(value));
    $("zoom").textContent = value ? "適合畫面" : "原尺寸";
    $("stage").scrollTo(0, 0);
  }

  function loadImage(item) {
    if (!imageCache.has(item.imageUrl)) {
      const image = new Image();
      image.decoding = "async";
      image.alt = item.title;
      image.src = item.imageUrl;
      const pending = image.decode().then(() => {
        readyImages.add(item.imageUrl);
        return image;
      }).catch((error) => {
        imageCache.delete(item.imageUrl);
        throw error;
      });
      imageCache.set(item.imageUrl, pending);
    }
    return imageCache.get(item.imageUrl);
  }

  async function preload(ticket) {
    const nearby = [-2, -1, 1, 2].map((offset) => items[index + offset]).filter(Boolean);
    const keep = new Set([items[index], ...nearby].filter(Boolean).map((item) => item.imageUrl));
    for (const key of imageCache.keys()) if (!keep.has(key)) { imageCache.delete(key); readyImages.delete(key); }
    $("preloadStatus").textContent = nearby.length ? "預載前後圖片…" : "";
    await Promise.allSettled(nearby.map(loadImage));
    if (ticket === generation) {
      const count = nearby.filter((item) => readyImages.has(item.imageUrl)).length;
      $("preloadStatus").textContent = count ? `已預載 ${count} 張` : "";
    }
  }

  function save(item, ticket) {
    $("saveStatus").textContent = "儲存進度…";
    const selectedCategory = category;
    saves = saves.catch(() => {}).then(() => api("/api/progress", { src: item.src, category: selectedCategory }));
    saves.then(() => {
      if (ticket === generation) $("saveStatus").textContent = `已記住 ${item.date} · 第 ${index + 1} 張`;
    }).catch((error) => {
      if (ticket === generation) $("saveStatus").textContent = `進度未儲存：${error.message}`;
    });
  }

  async function show(nextIndex) {
    const ticket = ++generation;
    detail = null;
    loading = true;
    index = Math.max(0, Math.min(nextIndex, items.length - 1));
    zoom(false);
    controls();
    $("stage").dataset.loading = "true";
    $("stage").setAttribute("aria-busy", "true");
    if (!items.length) {
      $("imageHost").replaceChildren();
      $("imageStatus").textContent = "這個分類目前沒有圖片。";
      $("filename").textContent = "沒有待檢查圖片";
      $("currentDate").textContent = "—";
      $("categoryBadge").textContent = category;
      $("prompt").textContent = "—";
      $("saveStatus").textContent = "有新圖片時，按「重新載入」。";
      $("preloadStatus").textContent = "";
      $("stage").setAttribute("aria-busy", "false");
      const emptyCategory = category;
      saves = saves.catch(() => {}).then(() => api("/api/progress", { src: null, category: emptyCategory }));
      saves.catch((error) => { if (ticket === generation) notice(error.message, true); });
      return;
    }
    const item = items[index];
    $("filename").textContent = item.title + item.src.slice(item.src.lastIndexOf("."));
    $("currentDate").textContent = item.date;
    $("currentDate").dateTime = item.addedAt;
    $("categoryBadge").textContent = item.category;
    $("collection").textContent = category === "全部" ? "無重力 / 自動 / 構圖" : category;
    $("dateJump").value = item.date;
    $("imageStatus").textContent = "載入圖片…";
    $("prompt").textContent = "載入中…";
    try {
      const [image, result] = await Promise.all([loadImage(item), api(`/api/item?src=${encodeURIComponent(item.src)}`)]);
      if (ticket !== generation) return;
      image.id = "reviewImage";
      image.tabIndex = 0;
      image.title = "點擊切換原尺寸 / 適合畫面";
      image.onclick = () => zoom(!zoomed);
      image.onkeydown = (event) => { if (event.key === "Enter") zoom(!zoomed); };
      $("imageHost").replaceChildren(image);
      $("imageStatus").textContent = "";
      $("prompt").textContent = result.prompt || "沒有同名 prompt。";
      $("stage").dataset.loading = "false";
      $("stage").setAttribute("aria-busy", "false");
      detail = { ...result, src: item.src };
      loading = false;
      controls();
      save(item, ticket);
      void preload(ticket);
    } catch (error) {
      if (ticket !== generation) return;
      loading = false;
      $("imageStatus").textContent = `無法載入：${error.message}`;
      $("stage").setAttribute("aria-busy", "false");
      $("saveStatus").textContent = "尚未儲存這張圖片的位置。";
      controls();
    }
  }

  function selectItems(preferred, anchor = "") {
    items = all.filter((item) => category === "全部" || item.category === category);
    const dates = new Map();
    for (const item of items) dates.set(item.date, (dates.get(item.date) || 0) + 1);
    $("dateJump").replaceChildren(...Array.from(dates, ([date, count]) => new Option(`${date} · ${count} 張`, date)));
    let nextIndex = items.findIndex((item) => item.src === preferred);
    if (nextIndex < 0) nextIndex = items.findIndex((item) => item.addedAt >= anchor);
    if (nextIndex < 0) nextIndex = Math.max(0, items.length - 1);
    return show(nextIndex);
  }

  async function catalog(data) {
    const result = data || await api("/api/catalog");
    all = result.images;
    deletedByCategory = result.deletedByCategory || {};
    category = result.progress.category || "全部";
    $("category").value = category;
    $("connection").hidden = true;
    await selectItems(result.progress.src, result.progress.addedAt || "");
  }

  $("previous").onclick = () => { if (!deleting && index > 0) void show(index - 1); };
  $("next").onclick = () => { if (!deleting && index + 1 < items.length) void show(index + 1); };
  $("zoom").onclick = () => zoom(!zoomed);
  $("category").onchange = () => {
    const item = items[index];
    category = $("category").value;
    notice("");
    void selectItems(item?.src, item?.addedAt || "");
  };
  $("dateJump").onchange = () => {
    const nextIndex = items.findIndex((item) => item.date === $("dateJump").value);
    if (nextIndex >= 0) void show(nextIndex);
  };
  $("jumpForm").onsubmit = (event) => {
    event.preventDefault();
    const page = Number($("pageNumber").value);
    if (!deleting && Number.isInteger(page) && page >= 1 && page <= items.length) void show(page - 1);
  };
  $("refresh").onclick = async () => {
    $("refresh").disabled = true;
    try { await saves.catch(() => {}); await catalog(); notice("清單已更新，依日期由舊到新排列。"); }
    catch (error) { notice(error.message, true); }
    finally { controls(); }
  };
  $("delete").onclick = async () => {
    if (deleting || loading || !detail) return;
    const selected = detail;
    deleting = true;
    controls();
    notice("");
    try {
      await saves.catch(() => {});
      const data = await api("/api/delete", { src: selected.src, signature: selected.signature, category });
      await catalog(data);
      notice(`已刪除 ${selected.src.split("/").at(-1)} 與同名 prompt。`);
    } catch (error) {
      notice(`刪除未完成：${error.message} 請重新載入確認清單。`, true);
      detail = null;
    } finally {
      deleting = false;
      controls();
    }
  };
  document.addEventListener("keydown", (event) => {
    const editing = event.target instanceof Element && (event.target.isContentEditable
      || event.target.closest("input, select, textarea, [role='textbox']"));
    if (event.isComposing || editing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    // The key labelled Delete on a MacBook sends Backspace; Fn+Delete sends Delete.
    if (event.key === "Backspace" || event.key === "Delete") {
      event.preventDefault();
      if (event.repeat || deleteKeyHeld) return;
      deleteKeyHeld = true;
      if (!deleting && !loading && detail) $("delete").click();
      return;
    }
    if (deleting) return;
    if (event.key === "ArrowLeft" && index > 0) { event.preventDefault(); void show(index - 1); }
    if (event.key === "ArrowRight" && index + 1 < items.length) { event.preventDefault(); void show(index + 1); }
  });
  document.addEventListener("keyup", (event) => {
    if (event.key === "Backspace" || event.key === "Delete") deleteKeyHeld = false;
  });
  window.addEventListener("blur", () => { deleteKeyHeld = false; });
  void catalog().catch((error) => {
    $("imageStatus").textContent = "請啟動本機 REVIEW 服務。";
    notice(`連線失敗：${error.message}`, true);
    controls();
  });
})();
