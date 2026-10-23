const MIN_SIZE = 1024;
const MAX_SIZE = 1048576;
const state = { file: null, previewUrl: "", config: "", qrKey: "", initialized: false, toastTimer: null };

const $ = (id) => document.getElementById(id);

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => node.classList.remove("show"), 3200);
}

function setPhotoInfo(file, uploaded = false) {
  $("dropzone").classList.toggle("hidden", Boolean(file));
  $("photoInfo").classList.toggle("hidden", !file);
  $("checksumRow").classList.toggle("hidden", !uploaded);
  if (!file) return;
  $("photoPreview").parentElement.classList.remove("hidden");
  $("fileName").textContent = file.name;
  $("fileSize").textContent = `${formatSize(file.size)}${file.size > MAX_SIZE ? " · 将自动压缩" : ""}`;
  $("sizeMeterFill").style.width = `${Math.min(100, Math.max(3, file.size / MAX_SIZE * 100))}%`;
  $("compressionHint").textContent = file.size > MAX_SIZE ? "上传前会在浏览器内压缩到合规大小" : "大小符合 OSS 上传限制";
  $("photoStatus").textContent = uploaded ? "已准备" : "处理中";
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);
  $("photoPreview").src = state.previewUrl;
}

function imageBlob(file, maxDimension, quality) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("浏览器无法压缩图片")), "image/jpeg", quality);
    };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error("无法读取图片，请换一张 JPG / PNG / WEBP")); };
    image.src = url;
  });
}

async function normalizeImage(file) {
  if (file.size <= MAX_SIZE) return file;
  const plans = [[1600, .82], [1200, .80], [1000, .76], [800, .72], [640, .68]];
  for (const [dimension, quality] of plans) {
    const blob = await imageBlob(file, dimension, quality);
    if (blob.size >= MIN_SIZE && blob.size <= MAX_SIZE) {
      return new File([blob], `${file.name.replace(/\.[^.]+$/, "")}.jpg`, { type: "image/jpeg" });
    }
  }
  throw new Error("自动压缩后仍不在 1KB～1MB 范围，请换一张图片");
}

async function uploadFile(file) {
  if (!file || !/\.(jpe?g|png|webp)$/i.test(file.name)) {
    toast("只支持 JPG、PNG、WEBP 图片");
    return;
  }
  state.file = file;
  setPhotoInfo(file);
  $("photoStatus").textContent = "压缩中";
  $("checksumRow").classList.add("hidden");
  try {
    const prepared = await normalizeImage(file);
    if (prepared !== file) {
      setPhotoInfo(prepared);
      toast(`已压缩为 ${formatSize(prepared.size)}，正在载入`);
    }
    const form = new FormData();
    form.append("photo", prepared, prepared.name);
    const response = await fetch("/api/photo", { method: "POST", body: form });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "图片上传失败");
    state.file = prepared;
    $("photoStatus").textContent = "已准备";
    $("checksumValue").textContent = result.md5;
    $("checksumRow").classList.remove("hidden");
    toast("证件照已准备好");
  } catch (error) {
    $("photoStatus").textContent = "失败";
    toast(error.message);
  }
}

function setProxyBadge(running) {
  const badge = $("proxyBadge");
  badge.className = `status-badge ${running ? "running" : "idle"}`;
  badge.innerHTML = `<span></span>${running ? "运行中" : "未运行"}`;
  $("startButton").disabled = running;
  $("stopButton").disabled = !running;
  $("ipInput").disabled = running;
  $("portInput").disabled = running;
}

function renderLogs(logs) {
  const box = $("logBox");
  if (!logs.length) {
    box.innerHTML = '<div class="log-empty">暂无日志，启动代理后会显示运行状态。</div>';
  } else {
    box.replaceChildren(...logs.map((line) => {
      const item = document.createElement("div");
      item.className = "log-line";
      if (/✓|✔|🎉|🔒/.test(line)) item.classList.add("success");
      if (/⚠/.test(line)) item.classList.add("warn");
      if (/✖|失败|错误/.test(line)) item.classList.add("error");
      item.textContent = line;
      return item;
    }));
    box.scrollTop = box.scrollHeight;
  }
  $("logCount").textContent = `${logs.length} 条`;
}

function renderStatus(data) {
  if (data.photo && !state.file) {
    $("dropzone").classList.add("hidden");
    $("photoInfo").classList.remove("hidden");
    $("photoPreview").parentElement.classList.add("hidden");
    $("fileName").textContent = data.photo.name;
    $("fileSize").textContent = formatSize(data.photo.size);
    $("sizeMeterFill").style.width = `${Math.min(100, data.photo.size / MAX_SIZE * 100)}%`;
    $("compressionHint").textContent = "已载入服务器，可直接启动代理";
    $("photoStatus").textContent = "已准备";
    $("checksumValue").textContent = data.photo.md5;
    $("checksumRow").classList.remove("hidden");
  }
  if (!$("ipInput").value) $("ipInput").value = data.ip || "";
  if (!state.initialized || data.running) {
    $("portInput").value = data.port || 51820;
    state.initialized = true;
  }
  setProxyBadge(data.running);
  renderLogs(data.logs || []);
  renderPhone(data);
  if (data.error) $("photoStatus").textContent = data.error;
}

function renderPhone(data) {
  state.config = data.config || "";
  $("configText").value = state.config;
  $("copyButton").disabled = !state.config;
  $("downloadButton").disabled = !state.config;
  const qrWrap = $("qrWrap");
  const qrKey = data.qrReady ? state.config : "";
  if (qrKey) {
    $("qrStatus").textContent = "可扫码导入";
    if (qrKey !== state.qrKey) {
      const img = document.createElement("img");
      img.src = `/api/qr?ts=${Date.now()}`;
      img.alt = "WireGuard 配置二维码";
      qrWrap.replaceChildren(img);
    }
  } else {
    $("qrStatus").textContent = data.running ? "正在生成二维码" : "等待代理启动";
    qrWrap.innerHTML = '<div class="qr-placeholder"><span>⌁</span><small>等待配置就绪</small></div>';
  }
  state.qrKey = qrKey;
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (response.ok) renderStatus(await response.json());
  } catch (_) { /* 网页服务重启时静默等待下一次轮询 */ }
}

async function startProxy() {
  try {
    const response = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: $("ipInput").value.trim(), port: Number($("portInput").value) })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "代理启动失败");
    toast("WireGuard 代理启动中，请等待二维码生成");
    await refresh();
  } catch (error) { toast(error.message); }
}

async function stopProxy() {
  await fetch("/api/stop", { method: "POST" });
  toast("代理已停止，记得关闭手机代理连接");
  await refresh();
}

function bind() {
  const input = $("fileInput");
  $("chooseButton").addEventListener("click", () => input.click());
  $("replaceButton").addEventListener("click", () => input.click());
  input.addEventListener("change", () => uploadFile(input.files[0]));
  const dropzone = $("dropzone");
  dropzone.addEventListener("click", (event) => { if (event.target.tagName !== "BUTTON") input.click(); });
  dropzone.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") input.click(); });
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
  dropzone.addEventListener("drop", (event) => uploadFile(event.dataTransfer.files[0]));
  $("startButton").addEventListener("click", startProxy);
  $("stopButton").addEventListener("click", stopProxy);
  $("copyButton").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(state.config);
      toast("WireGuard 配置已复制");
    } catch (_) {
      $("configText").select();
      toast("已选中文本，请按 Ctrl+C 复制");
    }
  });
  $("downloadButton").addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([state.config], { type: "text/plain" }));
    a.download = "wg-client.conf";
    setTimeout(() => URL.revokeObjectURL(a.href), 500);
    a.click();
  });
}

bind();
refresh();
setInterval(refresh, 1000);
