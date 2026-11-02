const images = window.__GALLERY_IMAGES__ || [];

// Only assign a URL once an image reaches the viewport. Native lazy loading
// may fetch images several screens away, competing with visible images.
const imageObserver = "IntersectionObserver" in window
  ? new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        loadCardImage(entry.target);
        imageObserver.unobserve(entry.target);
      });
    })
  : null;

function loadCardImage(image) {
  if (!image.dataset.src) return;
  image.loading = "eager";
  image.setAttribute("fetchpriority", "high");
  image.src = image.dataset.src;
  delete image.dataset.src;
}

function observeCardImages() {
  grid.querySelectorAll(".card-media > img[data-src]").forEach((image) => {
    const bounds = image.getBoundingClientRect();
    if (bounds.bottom > 0 && bounds.top < window.innerHeight
        && bounds.right > 0 && bounds.left < window.innerWidth) {
      loadCardImage(image);
    } else if (imageObserver) {
      imageObserver.observe(image);
    } else {
      image.src = image.dataset.src;
      delete image.dataset.src;
    }
  });
}

    const grid = document.querySelector("#grid");
    const filters = document.querySelector("#filters");
    const categoryMenu = document.querySelector("#categoryMenu");
    const search = document.querySelector("#search");
    const empty = document.querySelector("#empty");
    const pagination = document.querySelector("#pagination");
    const visibleCount = document.querySelector("#visibleCount");
    const totalCount = document.querySelector("#totalCount");
    const expandAllToggle = document.querySelector("#expandAllToggle");
    const lightbox = document.querySelector("#lightbox");
    const preview = document.querySelector("#preview");
    const previewCaption = document.querySelector("#previewCaption");
    const close = document.querySelector("#close");
    let descriptionDialog = null;
    const DEFAULT_CATEGORY = "全部";
    const CATEGORY_STORAGE_KEY = "gpt-gallery2-active-category";
    const PAGE_SIZE = 50;
    const categories = ["全部", "清新", "性感", "動漫", "故事"];
    let activeCategory = initialCategory();
    let currentImages = images;
    let currentGroups = [];
    let previewIndex = -1;
    let currentPage = 1;
    let touchStartX = 0;
    let touchStartY = 0;
    const expandedGroups = new Set();

    const totals = images.reduce((map, image) => {
      map[image.category] = (map[image.category] || 0) + 1;
      return map;
    }, {});

    function storedCategory() {
      try {
        return window.localStorage.getItem(CATEGORY_STORAGE_KEY);
      } catch (error) {
        return null;
      }
    }

    function rememberCategory(category) {
      try {
        window.localStorage.setItem(CATEGORY_STORAGE_KEY, category);
      } catch (error) {
        // Ignore storage failures so the gallery still works in private or restricted contexts.
      }
    }

    function initialCategory() {
      const savedCategory = storedCategory();
      if (savedCategory && categories.includes(savedCategory)) {
        return savedCategory;
      }
      return categories.includes(DEFAULT_CATEGORY) ? DEFAULT_CATEGORY : "全部";
    }

    function setActiveCategory(category) {
      activeCategory = category;
      currentPage = 1;
      rememberCategory(category);
      render();
    }

    function pageButton(label, page, options = {}) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "page-button";
      button.textContent = label;
      button.disabled = options.disabled || false;
      if (options.active) {
        button.classList.add("active");
        button.setAttribute("aria-current", "page");
      }
      button.addEventListener("click", () => {
        currentPage = page;
        render();
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
      return button;
    }

    function renderPagination(totalPages) {
      if (totalPages <= 1) {
        pagination.replaceChildren();
        return;
      }

      const controls = [pageButton("‹", currentPage - 1, { disabled: currentPage === 1 })];
      for (let page = 1; page <= totalPages; page += 1) {
        controls.push(pageButton(`PAGE ${page}`, page, { active: page === currentPage }));
      }
      controls.push(pageButton("›", currentPage + 1, { disabled: currentPage === totalPages }));
      pagination.replaceChildren(...controls);
    }

    function basenameKey(title) {
      const dashedGroupedMatch = title.match(/^(.+[a-z])-(\d+)$/);
      if (dashedGroupedMatch) {
        return dashedGroupedMatch[1];
      }

      const newGroupedMatch = title.match(/^(.+[a-z])\d+$/);
      if (newGroupedMatch) {
        return newGroupedMatch[1];
      }

      return title
        .replace(/-\d+$/, "")
        .replace(/[A-Za-z]+$/, "");
    }

    function variantKey(title) {
      const dashedGroupedMatch = title.match(/^(.+[a-z])-(\d+)$/);
      if (dashedGroupedMatch) {
        return ["", Number(dashedGroupedMatch[2]), title];
      }

      const newGroupedMatch = title.match(/^(.+[a-z])(\d+)$/);
      if (newGroupedMatch) {
        return ["", Number(newGroupedMatch[2]), title];
      }

      const copyMatch = title.match(/-(\d+)$/);
      const copyNumber = copyMatch ? Number(copyMatch[1]) : 0;
      const withoutCopy = title.replace(/-\d+$/, "");
      const variantMatch = withoutCopy.match(/[A-Za-z]+$/);
      const variant = variantMatch ? variantMatch[0] : "";
      return [variant, copyNumber, title];
    }

    function groupByBasename(items) {
      const groups = new Map();
      const order = [];

      for (const image of items) {
        const key = basenameKey(image.title || image.src);
        if (!groups.has(key)) {
          groups.set(key, []);
          order.push(key);
        }
        groups.get(key).push(image);
      }

      return order.map((key) => {
        const groupImages = groups.get(key).sort((left, right) => {
          const leftKey = variantKey(left.title || left.src);
          const rightKey = variantKey(right.title || right.src);
          return String(leftKey[0]).localeCompare(String(rightKey[0]), "zh-Hant")
            || Number(leftKey[1]) - Number(rightKey[1])
            || String(leftKey[2]).localeCompare(String(rightKey[2]), "zh-Hant");
        });
        return { key, images: groupImages };
      });
    }

    function displayItemsFor(groups) {
      return groups.flatMap((group) => {
        const isExpanded = expandedGroups.has(group.key);
        if (!isExpanded) {
          return [{
            image: group.images[0],
            groupKey: group.key,
            groupSize: group.images.length,
            isCollapsedGroup: group.images.length > 1,
            isExpandedGroup: false,
          }];
        }

        return group.images.map((image, index) => ({
          image,
          groupKey: group.key,
          groupIndex: index,
          groupSize: group.images.length,
          isCollapsedGroup: false,
          isExpandedGroup: group.images.length > 1,
        }));
      });
    }

    function makeChip(category) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.dataset.category = category;
      button.innerHTML = `${category}<span class="count">${category === "全部" ? images.length : totals[category]}</span>`;
      button.addEventListener("click", () => {
        setActiveCategory(category);
      });
      return button;
    }

    function makeOption(category) {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category;
      return option;
    }

    function showPreview(index) {
      if (!currentImages.length) return;
      previewIndex = (index + currentImages.length) % currentImages.length;
      const image = currentImages[previewIndex].image;
      preview.src = encodeURI(image.src);
      preview.alt = image.category;
      previewCaption.textContent = `${image.category} · ${image.title}`;
    }

    function openPreview(index) {
      showPreview(index);
      lightbox.classList.add("open");
    }

    function closePreview() {
      lightbox.classList.remove("open");
      preview.removeAttribute("src");
      previewIndex = -1;
    }

    function movePreview(direction) {
      if (!lightbox.classList.contains("open") || previewIndex < 0) return;
      showPreview(previewIndex + direction);
    }

    function handleSwipe(event) {
      if (!lightbox.classList.contains("open")) return;
      const touch = event.changedTouches[0];
      const deltaX = touch.clientX - touchStartX;
      const deltaY = touch.clientY - touchStartY;
      if (Math.abs(deltaX) < 50 || Math.abs(deltaX) < Math.abs(deltaY) * 1.2) return;
      movePreview(deltaX < 0 ? 1 : -1);
    }

    function markdownPathFor(imageSrc) {
      const url = new URL(imageSrc, window.location.href);
      url.pathname = url.pathname.replace(/\.[^/.]+$/, ".md");
      return url.href;
    }

    async function showMarkdownDescription(imageSrc) {
      const markdownPath = markdownPathFor(imageSrc);

      try {
        const response = await fetch(markdownPath, { cache: "no-store" });
        if (!response.ok) {
          showToast("無法讀取同名 md");
          return;
        }

        const text = await response.text();
        if (!text.trim()) {
          showToast("同名 md 沒有內容");
          return;
        }

        openDescriptionDialog(text, decodeURIComponent(new URL(markdownPath).pathname.split("/").pop()));
      } catch (error) {
        showToast("無法讀取同名 md");
      }
    }

    async function copyText(text) {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return;
      }

      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.left = "-9999px";
      textarea.style.position = "fixed";
      document.body.appendChild(textarea);
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      const copied = document.execCommand("copy");
      textarea.remove();
      if (!copied) {
        throw new Error("Copy command was not accepted");
      }
    }

    function ensureDescriptionDialog() {
      if (descriptionDialog) return descriptionDialog;

      const dialog = document.createElement("div");
      dialog.className = "description-dialog";
      dialog.innerHTML = `
        <section class="description-panel" role="dialog" aria-modal="true" aria-labelledby="descriptionTitle">
          <div class="description-head">
            <h2 id="descriptionTitle">描述內容</h2>
            <button class="description-close" type="button" aria-label="關閉">×</button>
          </div>
          <textarea class="description-text" readonly spellcheck="false"></textarea>
          <div class="description-actions">
            <button class="description-copy" type="button">Copy</button>
            <button class="description-select" type="button">全選文字</button>
          </div>
        </section>
      `;

      const textBox = dialog.querySelector(".description-text");
      dialog.querySelector(".description-close").addEventListener("click", closeDescriptionDialog);
      dialog.querySelector(".description-copy").addEventListener("click", async () => {
        try {
          await copyText(textBox.value);
          showToast("描述已複製");
        } catch (error) {
          selectDescriptionText();
          showToast("已全選文字，請手動複製");
        }
      });
      dialog.querySelector(".description-select").addEventListener("click", selectDescriptionText);
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDescriptionDialog();
      });
      dialog.addEventListener("keydown", (event) => {
        event.stopPropagation();
      });

      document.body.appendChild(dialog);
      descriptionDialog = dialog;
      return dialog;
    }

    function openDescriptionDialog(text, filename) {
      const dialog = ensureDescriptionDialog();
      dialog.querySelector("#descriptionTitle").textContent = filename;
      const textBox = dialog.querySelector(".description-text");
      textBox.value = text;
      dialog.classList.add("open");
      requestAnimationFrame(() => {
        selectDescriptionText();
      });
    }

    function closeDescriptionDialog() {
      if (!descriptionDialog) return;
      descriptionDialog.classList.remove("open");
    }

    function selectDescriptionText() {
      if (!descriptionDialog) return;
      const textBox = descriptionDialog.querySelector(".description-text");
      textBox.focus({ preventScroll: true });
      textBox.select();
      textBox.setSelectionRange(0, textBox.value.length);
    }

    function showToast(message) {
      let toast = document.querySelector(".toast");
      if (!toast) {
        toast = document.createElement("div");
        toast.className = "toast";
        document.body.appendChild(toast);
      }

      toast.textContent = message;
      toast.classList.add("show");
      clearTimeout(showToast.timer);
      showToast.timer = setTimeout(() => {
        toast.classList.remove("show");
      }, 2000);
    }

    function resizeMasonryCard(card) {
      const styles = getComputedStyle(grid);
      const rowHeight = Number.parseFloat(styles.gridAutoRows);
      const gap = Number.parseFloat(styles.rowGap);
      if (!rowHeight) return;

      const span = Math.ceil((card.getBoundingClientRect().height + gap) / (rowHeight + gap));
      card.style.gridRowEnd = `span ${span}`;
    }

    function resizeMasonry() {
      grid.querySelectorAll(".card").forEach(resizeMasonryCard);
    }

    function syncCardOrientation(card, image) {
      card.classList.toggle("landscape", image.naturalWidth > image.naturalHeight);
      resizeMasonryCard(card);
    }

    function idForGroupKey(groupKey) {
      let hash = 0;
      for (let index = 0; index < groupKey.length; index += 1) {
        hash = ((hash << 5) - hash + groupKey.charCodeAt(index)) | 0;
      }
      return `group-${Math.abs(hash).toString(36)}`;
    }

    function cardForGroupKey(groupKey) {
      return Array.from(grid.querySelectorAll(".card")).find((card) => card.dataset.groupKey === groupKey);
    }

    function renderAtGroupHash(groupKey, action) {
      action();
      render();

      const groupId = idForGroupKey(groupKey);
      const restorePosition = () => {
        const nextCard = cardForGroupKey(groupKey);
        if (!nextCard) return;

        if (window.location.hash !== `#${groupId}`) {
          window.history.replaceState(null, "", `#${groupId}`);
        }
        nextCard.scrollIntoView({ block: "start" });
      };

      requestAnimationFrame(() => {
        restorePosition();
        setTimeout(restorePosition, 120);
      });
    }

    function groupedKeysFor(groups) {
      return groups
        .filter((group) => group.images.length > 1)
        .map((group) => group.key);
    }

    function syncExpandAllToggle(groups) {
      const groupKeys = groupedKeysFor(groups);
      const allExpanded = groupKeys.length > 0 && groupKeys.every((key) => expandedGroups.has(key));
      const label = allExpanded ? "全部縮回" : "全部展開";

      expandAllToggle.disabled = groupKeys.length === 0;
      expandAllToggle.setAttribute("aria-label", label);
      expandAllToggle.title = label;
      expandAllToggle.querySelector("img").src = allExpanded ? "collapse-svgrepo-com.svg" : "expand-svgrepo-com.svg";
    }

    function toggleAllGroups() {
      const groupKeys = groupedKeysFor(currentGroups);
      const allExpanded = groupKeys.length > 0 && groupKeys.every((key) => expandedGroups.has(key));

      groupKeys.forEach((key) => {
        if (allExpanded) {
          expandedGroups.delete(key);
          return;
        }
        expandedGroups.add(key);
      });
      render();
    }

    function cardFor(item, index) {
      const { image } = item;
      const stackBadge = item.isCollapsedGroup ? `<span class="stack-badge">+${item.groupSize - 1}</span>` : "";
      const stackClass = item.isCollapsedGroup ? " stack" : "";
      const article = document.createElement("article");
      article.className = "card";
      article.classList.toggle("landscape", image.width > image.height);
      article.dataset.groupKey = item.groupKey;
      if (item.isCollapsedGroup || item.groupIndex === 0) {
        article.id = idForGroupKey(item.groupKey);
      }
      article.innerHTML = `
        <div class="card-media${stackClass}">
          <img loading="lazy" decoding="async" width="${image.width || 1024}" height="${image.height || 1536}" data-src="${encodeURI(image.src)}" alt="${image.category}" tabindex="0">
          ${stackBadge}
        </div>
        <div class="caption">
          <span class="category">${image.category}</span>
          <span class="caption-end">
            <span class="filename">${image.title}</span>
            <span class="card-actions">
              ${image.hasDescription ? '<button class="icon-button copy-desc" type="button" aria-label="複製描述" title="複製描述"><img src="language-json-svgrepo-com.svg" alt=""></button>' : ""}
              ${item.isExpandedGroup ? '<button class="icon-button collapse-group" type="button" aria-label="收合群組" title="收合群組"><img src="collapse-svgrepo-com.svg" alt=""></button>' : ""}
            </span>
          </span>
        </div>
      `;
      const cardImage = article.querySelector("img");
      cardImage.addEventListener("load", () => syncCardOrientation(article, cardImage));
      if (cardImage.complete && cardImage.naturalWidth) {
        syncCardOrientation(article, cardImage);
      }
      cardImage.addEventListener("click", () => {
        if (item.isCollapsedGroup) {
          renderAtGroupHash(item.groupKey, () => {
            expandedGroups.add(item.groupKey);
          });
          return;
        }
        openPreview(index);
      });
      cardImage.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        if (item.isCollapsedGroup) {
          renderAtGroupHash(item.groupKey, () => {
            expandedGroups.add(item.groupKey);
          });
          return;
        }
        openPreview(index);
      });
      article.querySelector(".copy-desc")?.addEventListener("click", (event) => {
        event.stopPropagation();
        showMarkdownDescription(image.src);
      });
      article.querySelector(".collapse-group")?.addEventListener("click", (event) => {
        event.stopPropagation();
        renderAtGroupHash(item.groupKey, () => {
          expandedGroups.delete(item.groupKey);
        });
      });
      article.querySelector(".card-actions")?.addEventListener("keydown", (event) => {
        event.stopPropagation();
      });
      return article;
    }

    function render() {
      imageObserver?.disconnect();
      const query = search.value.trim().toLowerCase();
      const filtered = images.filter((image) => {
        const matchCategory = activeCategory === "全部" || image.category === activeCategory;
        const matchQuery = !query || `${image.category} ${image.title}`.toLowerCase().includes(query);
        return matchCategory && matchQuery;
      });
      currentGroups = groupByBasename(filtered);
      const displayItems = displayItemsFor(currentGroups);
      const totalPages = Math.max(1, Math.ceil(displayItems.length / PAGE_SIZE));
      currentPage = Math.min(currentPage, totalPages);
      const pageStart = (currentPage - 1) * PAGE_SIZE;
      currentImages = displayItems.slice(pageStart, pageStart + PAGE_SIZE);

      document.querySelectorAll(".chip").forEach((chip) => {
        chip.classList.toggle("active", chip.dataset.category === activeCategory);
      });
      categoryMenu.value = activeCategory;
      grid.replaceChildren(...currentImages.map(cardFor));
      resizeMasonry();
      observeCardImages();
      empty.style.display = currentImages.length ? "none" : "block";
      visibleCount.textContent = currentImages.length;
      totalCount.textContent = images.length;
      syncExpandAllToggle(currentGroups);
      renderPagination(totalPages);
    }

    filters.replaceChildren(...categories.map(makeChip));
    categoryMenu.replaceChildren(...categories.map(makeOption));
    categoryMenu.addEventListener("change", () => {
      setActiveCategory(categoryMenu.value);
    });
    search.addEventListener("input", () => {
      currentPage = 1;
      render();
    });
    expandAllToggle.addEventListener("click", toggleAllGroups);
    window.addEventListener("resize", resizeMasonry);
    close.addEventListener("click", closePreview);
    lightbox.addEventListener("click", (event) => {
      if (event.target === lightbox) closePreview();
    });
    lightbox.addEventListener("touchstart", (event) => {
      const touch = event.changedTouches[0];
      touchStartX = touch.clientX;
      touchStartY = touch.clientY;
    }, { passive: true });
    lightbox.addEventListener("touchend", handleSwipe, { passive: true });
    window.addEventListener("keydown", (event) => {
      if (descriptionDialog?.classList.contains("open")) {
        if (event.key === "Escape") closeDescriptionDialog();
        return;
      }
      if (event.key === "Escape") closePreview();
      if (event.key === "ArrowLeft") movePreview(-1);
      if (event.key === "ArrowRight") movePreview(1);
    });
    render();
