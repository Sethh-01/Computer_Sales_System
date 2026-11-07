const state = {
  products: [], orders: [], activeView: "dashboard", toastTimer: null,
  storeProducts: [], storeCatalog: {}, cart: {}, customer: null, registering: false, filtersLoaded: false,
  lastSecurityEventId: 0, securityPollTimer: null
};
const $ = (selector, root = document) => root.querySelector(selector);
const money = (amount) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount || 0);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers }
  });
  if (response.status === 401 && !["/api/login", "/api/customer/login"].includes(path)) {
    showLogin();
    throw new Error("សូមចូលគណនីម្ដងទៀត");
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("ម៉ាស៊ីនមេបានផ្ញើទិន្នន័យមិនត្រឹមត្រូវ");
  }
  if (!response.ok) throw new Error(payload.error || "មានបញ្ហាក្នុងការភ្ជាប់ទៅប្រព័ន្ធ");
  return payload;
}

function showLogin() {
  $("#login-screen").classList.remove("hidden");
  $("#app-shell").classList.add("hidden");
  $("#storefront-screen").classList.add("hidden");
}

function showApp() {
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  $("#storefront-screen").classList.add("hidden");
}

function showStorefront() {
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.add("hidden");
  $("#storefront-screen").classList.remove("hidden");
}

function updateCustomerActions() {
  const signedIn = Boolean(state.customer);
  ["customer-orders-button", "customer-profile-button", "customer-logout-button"]
    .forEach((id) => $(`#${id}`).classList.toggle("hidden", !signedIn));
  $("#customer-login-button").classList.toggle("hidden", signedIn);
}

function renderStoreProducts(products) {
  const target = $("#store-products");
  if (!products.length) {
    target.innerHTML = `<p class="empty-state">មិនមានផលិតផលត្រូវនឹងការស្វែងរកទេ</p>`;
    return;
  }
  target.innerHTML = products.map((product) => `
    <article class="store-product-card">
      <button class="product-photo" type="button" data-details="${product.id}" aria-label="មើល ${escapeHTML(product.name)}">
        ${product.image_url ? `<img src="${escapeHTML(product.image_url)}" alt="${escapeHTML(product.name)}" loading="lazy">` : `<span>💻</span>`}
      </button>
      <div class="store-product-info">
        <span class="product-category">${escapeHTML(product.category)}${product.brand ? ` · ${escapeHTML(product.brand)}` : ""}</span>
        <button class="product-title" type="button" data-details="${product.id}">${escapeHTML(product.name)}</button>
        <p class="product-sub">${escapeHTML(product.sku)} · ស្តុក ${product.stock}</p>
        <div class="store-product-bottom"><strong>${money(product.price)}</strong><button class="button button-primary" type="button" data-cart-add="${product.id}" ${product.stock < 1 ? "disabled" : ""}>ដាក់ក្នុងកន្ត្រក</button></div>
      </div>
    </article>`).join("");
}

async function loadStoreProducts() {
  const params = new URLSearchParams();
  const search = $("#store-search").value.trim();
  const category = $("#store-category").value;
  const brand = $("#store-brand").value;
  const min = $("#store-min-price").value;
  const max = $("#store-max-price").value;
  if (search) params.set("search", search);
  if (category) params.set("category", category);
  if (brand) params.set("brand", brand);
  if (min) params.set("min_price", min);
  if (max) params.set("max_price", max);
  const result = await api(`/api/storefront/products?${params}`);
  state.storeProducts = result.products;
  for (const product of result.products) state.storeCatalog[product.id] = product;
  if (!state.filtersLoaded) {
    $("#store-category").innerHTML += result.categories.map((value) => `<option value="${escapeHTML(value)}">${escapeHTML(value)}</option>`).join("");
    $("#store-brand").innerHTML += result.brands.map((value) => `<option value="${escapeHTML(value)}">${escapeHTML(value)}</option>`).join("");
    state.filtersLoaded = true;
  }
  $("#store-message").textContent = `${result.products.length} ផលិតផល`;
  renderStoreProducts(result.products);
}

function updateCartCount() {
  const count = Object.values(state.cart).reduce((total, quantity) => total + quantity, 0);
  $("#cart-count").textContent = count;
}

function renderCart() {
  const products = Object.values(state.cart)
    .map((quantity) => quantity);
  const rows = Object.entries(state.cart).map(([id, quantity]) => {
    const product = state.storeCatalog[id] || state.storeProducts.find((item) => item.id === Number(id));
    if (!product) return "";
    return `<div class="cart-row"><div><b>${escapeHTML(product.name)}</b><small>${money(product.price)}</small></div>
      <div class="cart-quantity"><button type="button" data-cart-change="${id}" data-delta="-1" aria-label="បន្ថយ">−</button><span>${quantity}</span><button type="button" data-cart-change="${id}" data-delta="1" aria-label="បន្ថែម">+</button></div>
      <button class="remove-item" type="button" data-cart-remove="${id}" aria-label="លុប">×</button></div>`;
  }).join("");
  $("#cart-items").innerHTML = rows || `<p class="empty-state">កន្ត្រកទំនិញទទេ</p>`;
  const total = Object.entries(state.cart).reduce((sum, [id, quantity]) => {
    const product = state.storeCatalog[id] || state.storeProducts.find((item) => item.id === Number(id));
    return sum + (product ? product.price * quantity : 0);
  }, 0);
  $("#cart-total strong").textContent = money(total);
  $("#checkout-button").disabled = !products.length;
  updateCartCount();
}

function renderCustomerOrders(orders) {
  const labels = { processing: "កំពុងរៀបចំ", shipping: "កំពុងដឹកជញ្ជូន", delivered: "បានដឹកជញ្ជូន" };
  $("#customer-orders-list").innerHTML = orders.length ? orders.map((order) => `
    <article class="customer-order-card">
      <div class="order-card-top"><div><b>${escapeHTML(order.order_number)}</b><small>${new Date(`${order.created_at.replace(" ", "T")}Z`).toLocaleString("km-KH")}</small></div><strong>${money(order.total)}</strong></div>
      <p>${order.items.map((item) => `${escapeHTML(item.name)} × ${item.quantity}`).join(" · ")}</p>
      <div class="order-tracking"><span class="${order.status === "processing" ? "current" : "complete"}">១. កំពុងរៀបចំ</span><span class="${order.status === "shipping" || order.status === "delivered" ? "current" : ""}">២. កំពុងដឹកជញ្ជូន</span><span class="${order.status === "delivered" ? "complete" : ""}">៣. បានទទួល</span></div>
      <small>ស្ថានភាព៖ ${labels[order.status] || escapeHTML(order.status)} · ការទូទាត់៖ ${escapeHTML(order.payment_method)} (${escapeHTML(order.payment_status)}) · ${escapeHTML(order.shipping_address)}</small>
    </article>`).join("") : `<p class="empty-state">មិនទាន់មានការបញ្ជាទិញទេ</p>`;
}

function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}

function showError(element, error) {
  element.textContent = error.message || String(error);
}

function stockBadge(stock) {
  const low = stock <= 5;
  return `<span class="stock-badge ${low ? "stock-low" : "stock-good"}">${low ? "ជិតអស់ · " : ""}${stock}</span>`;
}

function productRows(products, dashboard = false) {
  if (!products.length) return `<tr><td class="empty-state" colspan="${dashboard ? 5 : 6}">មិនមានផលិតផលនៅឡើយទេ</td></tr>`;
  return products.map((product) => `<tr>
    <td><span class="product-name">${escapeHTML(product.name)}</span><span class="product-sub">${escapeHTML(product.sku)}</span></td>
    ${dashboard ? "" : `<td>${escapeHTML(product.sku)}</td>`}
    <td>${escapeHTML(product.category)}</td><td>${money(product.price)}</td><td>${stockBadge(product.stock)}</td>
    ${dashboard ? `<td><span class="status-badge">កំពុងលក់</span></td>` : `<td><div class="table-actions"><button class="small-button" data-edit="${product.id}">កែប្រែ</button><button class="small-button danger" data-archive="${product.id}">ដកចេញ</button><button class="small-button" data-sell="${product.id}">លក់</button></div></td>`}
  </tr>`).join("");
}

function orderRows(orders, dashboard = false) {
  if (!orders.length) return `<tr><td class="empty-state" colspan="${dashboard ? 5 : 6}">មិនទាន់មានការលក់នៅឡើយទេ</td></tr>`;
  return orders.map((order) => {
    const itemText = order.items.map((item) => `${escapeHTML(item.name)} × ${item.quantity}`).join(", ");
    const date = new Date(`${order.created_at.replace(" ", "T")}Z`).toLocaleString("km-KH", { dateStyle: "medium", timeStyle: "short" });
    const status = dashboard ? "" : `<td><select class="order-status-select" data-order-status="${order.id}">
      <option value="processing" ${order.status === "processing" ? "selected" : ""}>កំពុងរៀបចំ</option>
      <option value="shipping" ${order.status === "shipping" ? "selected" : ""}>កំពុងដឹកជញ្ជូន</option>
      <option value="delivered" ${order.status === "delivered" ? "selected" : ""}>បានដឹកជញ្ជូន</option>
    </select></td>`;
    return `<tr><td><span class="product-name">${escapeHTML(order.order_number)}</span></td><td>${escapeHTML(order.customer_name || "អតិថិជនទូទៅ")}</td><td>${itemText}</td><td>${date}</td><td><b>${money(order.total)}</b></td>${status}</tr>`;
  }).join("");
}

async function loadDashboard() {
  const [metrics, productData, orderData, securityData] = await Promise.all([
    api("/api/dashboard"), api("/api/products"), api("/api/orders"), api("/api/security/events")
  ]);
  state.products = productData.products;
  state.orders = orderData.orders;
  $("#metric-revenue").textContent = money(metrics.today_revenue);
  $("#metric-orders").textContent = metrics.today_orders;
  $("#metric-products").textContent = metrics.active_products;
  $("#metric-low-stock").textContent = metrics.low_stock_products;
  $("#dashboard-products").innerHTML = productRows(state.products.slice(0, 5), true);
  $("#dashboard-orders").innerHTML = orderRows(state.orders.slice(0, 5), true);
  renderSecurityEvents(securityData, false);
}

function renderSecurityEvents(data, announce = true) {
  const events = data.events || [];
  const nextId = events.reduce((max, event) => Math.max(max, event.id), state.lastSecurityEventId);
  const unseen = state.lastSecurityEventId
    ? events.filter((event) => event.id > state.lastSecurityEventId)
    : [];
  state.lastSecurityEventId = nextId;
  $("#security-channel-status").textContent = data.telegram_configured
    ? "Telegram ត្រូវបានកំណត់ • ត្រួតពិនិត្យរៀងរាល់ ១៥ វិនាទី"
    : "Telegram មិនទាន់ត្រូវបានកំណត់ • សូមបន្ថែម TELEGRAM_BOT_TOKEN និង TELEGRAM_CHAT_ID";
  $("#security-live-badge").classList.toggle("security-live-disabled", !data.telegram_configured);
  $("#security-event-list").innerHTML = events.length ? events.map((event) => `
    <article class="security-event ${event.severity === "critical" ? "security-event-critical" : ""}">
      <span class="security-event-icon">${event.severity === "critical" ? "!" : "•"}</span>
      <div class="security-event-copy"><b>${escapeHTML(event.category)}</b><span>${escapeHTML(event.message)}</span><small>${escapeHTML(event.route || "system")} · ${new Date(`${event.created_at.replace(" ", "T")}Z`).toLocaleString("km-KH")}</small></div>
      <span class="security-severity">${event.severity === "critical" ? "ធ្ងន់ធ្ងរ" : "ព្រមាន"}</span>
    </article>`).join("") : `<p class="empty-state">មិនទាន់មានបញ្ហាសុវត្ថិភាពដែលបានកត់ត្រាទេ</p>`;
  if (announce && unseen.length) {
    notify(`មាន security alert ថ្មី: ${unseen[0].category}`);
  }
}

async function pollSecurityEvents() {
  if (state.activeView !== "dashboard" || $("#app-shell").classList.contains("hidden")) return;
  try {
    renderSecurityEvents(await api("/api/security/events"));
  } catch (error) {
    notify(error.message);
  }
}

function startSecurityPolling() {
  clearInterval(state.securityPollTimer);
  state.securityPollTimer = setInterval(pollSecurityEvents, 15_000);
}

async function loadProducts() {
  const search = $("#product-search").value.trim();
  const result = await api(`/api/products?search=${encodeURIComponent(search)}`);
  $("#products-table").innerHTML = productRows(result.products);
  $("#product-count").textContent = `${result.products.length} ផលិតផល`;
}

async function loadOrders() {
  const result = await api("/api/orders");
  state.orders = result.orders;
  $("#orders-table").innerHTML = orderRows(result.orders);
}

async function navigate(view) {
  state.activeView = view;
  document.querySelectorAll(".view").forEach((section) => section.classList.toggle("hidden", section.id !== `view-${view}`));
  document.querySelectorAll(".nav-link").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  try {
    if (view === "dashboard") await loadDashboard();
    if (view === "products") await loadProducts();
    if (view === "orders") await loadOrders();
  } catch (error) { notify(error.message); }
}

function openProductDialog(product = null) {
  const form = $("#product-form");
  form.reset();
  form.elements.id.value = product?.id || "";
  if (product) {
    form.elements.name.value = product.name;
    form.elements.sku.value = product.sku;
    form.elements.category.value = product.category;
    form.elements.brand.value = product.brand || "";
    form.elements.description.value = product.description || "";
    form.elements.image_url.value = product.image_url || "";
    form.elements.price.value = product.price.toFixed(2);
    form.elements.stock.value = product.stock;
  }
  $("#product-dialog-title").textContent = product ? "កែប្រែផលិតផល" : "បន្ថែមផលិតផល";
  $("#product-form-error").textContent = "";
  $("#product-dialog").showModal();
}

function addSaleItem(productId = "") {
  if (!state.products.length) {
    notify("សូមបន្ថែមផលិតផលជាមុនសិន");
    return;
  }
  const row = document.createElement("div");
  row.className = "sale-item";
  row.innerHTML = `<select aria-label="ផលិតផល">${state.products.map((product) => `<option value="${product.id}" ${String(product.id) === String(productId) ? "selected" : ""} ${product.stock === 0 ? "disabled" : ""}>${escapeHTML(product.name)} (${escapeHTML(product.sku)}) · ${money(product.price)} · ស្តុក ${product.stock}</option>`).join("")}</select><input aria-label="ចំនួន" type="number" min="1" step="1" value="1"><button class="remove-item" type="button" aria-label="លុប">×</button>`;
  row.querySelector(".remove-item").addEventListener("click", () => { row.remove(); updateSaleTotal(); });
  row.querySelectorAll("select,input").forEach((element) => element.addEventListener("change", updateSaleTotal));
  $("#sale-items").append(row);
  updateSaleTotal();
}

function updateSaleTotal() {
  let total = 0;
  document.querySelectorAll(".sale-item").forEach((row) => {
    const product = state.products.find((item) => item.id === Number(row.querySelector("select").value));
    const quantity = Number(row.querySelector("input").value);
    if (product && Number.isInteger(quantity) && quantity > 0) total += product.price * quantity;
  });
  $("#sale-total strong").textContent = money(total);
}

function openSaleDialog(productId = "") {
  $("#sale-form").reset();
  $("#sale-items").replaceChildren();
  $("#sale-form-error").textContent = "";
  $("#sale-dialog").showModal();
  addSaleItem(productId);
}

async function openProductDetails(productId) {
  const { product } = await api(`/api/storefront/products/${productId}`);
  state.storeCatalog[product.id] = product;
  const reviews = product.reviews.length
    ? product.reviews.map((review) => `<article class="review-entry"><b>${escapeHTML(review.customer_name)}</b><span>${"★".repeat(review.rating)}${"☆".repeat(5 - review.rating)}</span><p>${escapeHTML(review.comment || "គ្មានមតិបន្ថែម")}</p></article>`).join("")
    : `<p class="muted">មិនទាន់មានការវាយតម្លៃ</p>`;
  $("#product-detail-content").innerHTML = `
    <div class="dialog-heading"><div><p class="eyebrow">${escapeHTML(product.category)} · ${escapeHTML(product.brand)}</p><h2>${escapeHTML(product.name)}</h2></div><button class="icon-button" type="button" data-close="product-detail-dialog" aria-label="បិទ">×</button></div>
    ${product.image_url ? `<img class="detail-image" src="${escapeHTML(product.image_url)}" alt="${escapeHTML(product.name)}">` : `<div class="detail-placeholder">💻</div>`}
    <p>${escapeHTML(product.description || "សូមទាក់ទងហាងសម្រាប់ព័ត៌មានបន្ថែម។")}</p>
    <p class="detail-price">${money(product.price)} <span class="muted">· នៅសល់ ${product.stock} · SKU ${escapeHTML(product.sku)}</span></p>
    <button class="button button-primary button-wide" type="button" data-cart-add="${product.id}" ${product.stock < 1 ? "disabled" : ""}>ដាក់ក្នុងកន្ត្រក</button>
    <section class="review-section"><h3>ការវាយតម្លៃ និងមតិយោបល់</h3>${reviews}
      ${state.customer ? `<form class="review-form" data-review-product="${product.id}"><label>វាយតម្លៃ<select name="rating"><option value="5">៥ ★</option><option value="4">៤ ★</option><option value="3">៣ ★</option><option value="2">២ ★</option><option value="1">១ ★</option></select></label><label>មតិយោបល់<textarea name="comment" rows="2" maxlength="1000"></textarea></label><button class="button button-outline" type="submit">ផ្ញើមតិយោបល់</button><p class="form-error" role="alert"></p></form>` : `<p class="muted">ចូលគណនីដើម្បីសរសេរមតិយោបល់បន្ទាប់ពីទិញផលិតផលនេះ។</p>`}
    </section>`;
  $("#product-detail-dialog").showModal();
}

function openCustomerAuth(registering = false) {
  state.registering = registering;
  const form = $("#customer-auth-form");
  form.reset();
  $("#customer-auth-error").textContent = "";
  $("#customer-register-fields").classList.toggle("hidden", !registering);
  $("#customer-auth-title").textContent = registering ? "បង្កើតគណនីអតិថិជន" : "ចូលគណនីអតិថិជន";
  $("#customer-auth-toggle").textContent = registering ? "មានគណនីរួចហើយ? ចូល" : "បង្កើតគណនីថ្មី";
  form.elements.password.autocomplete = registering ? "new-password" : "current-password";
  form.querySelector('button[type="submit"]').textContent = registering ? "បង្កើតគណនី" : "ចូលគណនី";
  $("#customer-auth-dialog").showModal();
}

async function openCustomerProfile() {
  const { profile } = await api("/api/customer/profile");
  const form = $("#customer-profile-form");
  form.elements.full_name.value = profile.full_name;
  form.elements.email.value = profile.email;
  form.elements.phone.value = profile.phone;
  form.elements.address.value = profile.address;
  $("#profile-error").textContent = "";
  $("#customer-profile-dialog").showModal();
}

async function showCustomerOrders() {
  const { orders } = await api("/api/customer/orders");
  renderCustomerOrders(orders);
  $("#customer-orders-section").classList.remove("hidden");
  $("#store-products").classList.add("hidden");
  document.querySelector(".store-filters").classList.add("hidden");
  $(".store-hero").classList.add("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
    showApp();
    $("#today-label").textContent = new Date().toLocaleDateString("km-KH", { dateStyle: "full" });
    await navigate("dashboard");
    startSecurityPolling();
  } catch (error) { showError($("#login-error"), error); }
});

$("#logout-button").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (error) { notify(error.message); }
  clearInterval(state.securityPollTimer);
  showLogin();
  $("#login-form").elements.password.value = "";
});

document.querySelectorAll(".nav-link").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
document.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => {
  navigate(button.dataset.go);
  if (button.dataset.go === "products" && button.textContent.includes("លក់")) {
    setTimeout(openSaleDialog, 120);
  }
}));
$("#add-product-button").addEventListener("click", () => openProductDialog());
$("#product-search").addEventListener("input", () => loadProducts().catch((error) => notify(error.message)));

$("#product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const payload = {
    name: form.elements.name.value, sku: form.elements.sku.value,
    category: form.elements.category.value, price: Number(form.elements.price.value),
    brand: form.elements.brand.value, description: form.elements.description.value,
    image_url: form.elements.image_url.value,
    stock: Number(form.elements.stock.value)
  };
  try {
    await api(id ? `/api/products/${id}` : "/api/products", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) });
    $("#product-dialog").close();
    notify(id ? "បានកែប្រែផលិតផលរួចរាល់" : "បានបន្ថែមផលិតផលរួចរាល់");
    await navigate(state.activeView);
  } catch (error) { showError($("#product-form-error"), error); }
});

$("#products-table").addEventListener("click", async (event) => {
  const editId = event.target.dataset.edit;
  const archiveId = event.target.dataset.archive;
  const sellId = event.target.dataset.sell;
  if (editId) openProductDialog(state.products.find((product) => product.id === Number(editId)));
  if (sellId) openSaleDialog(sellId);
  if (archiveId && confirm("តើអ្នកប្រាកដថាចង់ដកផលិតផលនេះចេញពីការលក់មែនទេ?")) {
    try {
      await api(`/api/products/${archiveId}`, { method: "DELETE" });
      notify("បានដកផលិតផលចេញពីការលក់");
      await navigate("products");
    } catch (error) { notify(error.message); }
  }
});
$("#orders-table").addEventListener("change", async (event) => {
  const select = event.target.closest("[data-order-status]");
  if (!select) return;
  try {
    await api(`/api/orders/${select.dataset.orderStatus}/status`, {
      method: "PUT", body: JSON.stringify({ status: select.value })
    });
    notify("បានកែប្រែស្ថានភាពការបញ្ជាទិញ");
  } catch (error) {
    notify(error.message);
    await loadOrders();
  }
});

$("#add-sale-item").addEventListener("click", () => addSaleItem());
$("#sale-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const rows = [...document.querySelectorAll(".sale-item")];
  const items = rows.map((row) => ({
    product_id: Number(row.querySelector("select").value),
    quantity: Number(row.querySelector("input").value)
  }));
  if (!items.length || items.some((item) => !Number.isInteger(item.quantity) || item.quantity <= 0)) {
    $("#sale-form-error").textContent = "សូមជ្រើសផលិតផល និងបញ្ចូលចំនួនឲ្យបានត្រឹមត្រូវ";
    return;
  }
  try {
    const result = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({ customer_name: event.currentTarget.elements.customer_name.value, items })
    });
    $("#sale-dialog").close();
    notify(`លក់បានជោគជ័យ · ${result.order.order_number}`);
    await loadDashboard();
    if (state.activeView === "products") await loadProducts();
  } catch (error) { showError($("#sale-form-error"), error); }
});

document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));

$("#open-storefront").addEventListener("click", () => showStorefront());
$("#admin-login-button").addEventListener("click", () => showLogin());
$("#store-home").addEventListener("click", (event) => {
  event.preventDefault();
  $("#customer-orders-section").classList.add("hidden");
  $("#store-products").classList.remove("hidden");
  $(".store-filters").classList.remove("hidden");
  $(".store-hero").classList.remove("hidden");
});
$("#customer-login-button").addEventListener("click", () => openCustomerAuth());
$("#customer-auth-toggle").addEventListener("click", () => openCustomerAuth(!state.registering));
$("#customer-auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    email: form.elements.email.value,
    password: form.elements.password.value
  };
  if (state.registering) {
    payload.full_name = form.elements.full_name.value;
    payload.phone = form.elements.phone.value;
  }
  try {
    const result = await api(state.registering ? "/api/customer/register" : "/api/customer/login", {
      method: "POST", body: JSON.stringify(payload)
    });
    state.customer = result.profile;
    $("#customer-auth-dialog").close();
    updateCustomerActions();
    showStorefront();
    notify(state.registering ? "បានបង្កើតគណនីរួចរាល់" : "បានចូលគណនីរួចរាល់");
  } catch (error) { showError($("#customer-auth-error"), error); }
});
$("#customer-logout-button").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
    state.customer = null;
    updateCustomerActions();
    notify("បានចាកចេញពីគណនី");
  } catch (error) { notify(error.message); }
});
$("#customer-profile-button").addEventListener("click", () => openCustomerProfile().catch((error) => notify(error.message)));
$("#customer-profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/customer/profile", {
      method: "PUT",
      body: JSON.stringify({
        full_name: form.elements.full_name.value,
        phone: form.elements.phone.value,
        address: form.elements.address.value
      })
    });
    $("#customer-profile-dialog").close();
    notify("បានរក្សាទុកព័ត៌មានគណនី");
  } catch (error) { showError($("#profile-error"), error); }
});
$("#customer-orders-button").addEventListener("click", () => showCustomerOrders().catch((error) => notify(error.message)));
$("#close-orders").addEventListener("click", () => $("#store-home").click());
$("#store-search").addEventListener("input", () => {
  clearTimeout(state.storeSearchTimer);
  state.storeSearchTimer = setTimeout(() => loadStoreProducts().catch((error) => notify(error.message)), 180);
});
["store-category", "store-brand", "store-min-price", "store-max-price"].forEach((id) => {
  $(`#${id}`).addEventListener("change", () => loadStoreProducts().catch((error) => notify(error.message)));
});
$("#store-products").addEventListener("click", (event) => {
  const addButton = event.target.closest("[data-cart-add]");
  const detailsButton = event.target.closest("[data-details]");
  if (addButton) {
    const productId = Number(addButton.dataset.cartAdd);
    state.cart[productId] = (state.cart[productId] || 0) + 1;
    updateCartCount();
    notify("បានបន្ថែមទំនិញក្នុងកន្ត្រក");
  } else if (detailsButton) {
    openProductDetails(detailsButton.dataset.details).catch((error) => notify(error.message));
  }
});
$("#product-detail-content").addEventListener("click", (event) => {
  const addButton = event.target.closest("[data-cart-add]");
  if (addButton) {
    const id = Number(addButton.dataset.cartAdd);
    state.cart[id] = (state.cart[id] || 0) + 1;
    updateCartCount();
    notify("បានបន្ថែមទំនិញក្នុងកន្ត្រក");
  }
});
$("#product-detail-content").addEventListener("submit", async (event) => {
  if (!event.target.matches("[data-review-product]")) return;
  event.preventDefault();
  const form = event.target;
  try {
    await api(`/api/products/${form.dataset.reviewProduct}/reviews`, {
      method: "POST",
      body: JSON.stringify({ rating: Number(form.elements.rating.value), comment: form.elements.comment.value })
    });
    await openProductDetails(form.dataset.reviewProduct);
    notify("បានបន្ថែមមតិយោបល់");
  } catch (error) { showError(form.querySelector(".form-error"), error); }
});
$("#cart-button").addEventListener("click", () => {
  renderCart();
  $("#cart-error").textContent = "";
  $("#cart-dialog").showModal();
});
$("#cart-items").addEventListener("click", (event) => {
  const change = event.target.closest("[data-cart-change]");
  const remove = event.target.closest("[data-cart-remove]");
  if (change) {
    const id = change.dataset.cartChange;
    state.cart[id] = (state.cart[id] || 0) + Number(change.dataset.delta);
    if (state.cart[id] <= 0) delete state.cart[id];
  }
  if (remove) delete state.cart[remove.dataset.cartRemove];
  renderCart();
});
$("#checkout-button").addEventListener("click", async () => {
  if (!state.customer) {
    $("#cart-dialog").close();
    openCustomerAuth();
    return;
  }
  try {
    const { profile } = await api("/api/customer/profile");
    $("#checkout-form").elements.shipping_address.value = profile.address;
    $("#checkout-error").textContent = "";
    $("#cart-dialog").close();
    $("#checkout-dialog").showModal();
  } catch (error) { notify(error.message); }
});
$("#checkout-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const items = Object.entries(state.cart).map(([product_id, quantity]) => ({
    product_id: Number(product_id), quantity
  }));
  try {
    const { order } = await api("/api/customer/orders", {
      method: "POST",
      body: JSON.stringify({
        items,
        shipping_address: form.elements.shipping_address.value,
        payment_method: form.elements.payment_method.value
      })
    });
    state.cart = {};
    $("#checkout-dialog").close();
    updateCartCount();
    await loadStoreProducts();
    notify(`បានបញ្ជាទិញរួចរាល់ · ${order.order_number}`);
    await showCustomerOrders();
  } catch (error) { showError($("#checkout-error"), error); }
});

loadStoreProducts().catch((error) => notify(error.message));
api("/api/session").then(async (session) => {
  if (session.role === "admin") {
    showApp();
    $("#today-label").textContent = new Date().toLocaleDateString("km-KH", { dateStyle: "full" });
    await navigate("dashboard");
    startSecurityPolling();
    return;
  }
  if (session.role === "customer") state.customer = session.profile;
  updateCustomerActions();
  showStorefront();
}).catch((error) => notify(error.message));
