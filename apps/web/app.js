const state = { products: [], orders: [], user: null, activeView: "dashboard", toastTimer: null };
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
  if (response.status === 401 && path !== "/api/login") {
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
  state.user = null;
  $("#accounts-nav").classList.add("hidden");
  $("#login-screen").classList.remove("hidden");
  $("#app-shell").classList.add("hidden");
}

function setCurrentUser(user) {
  state.user = user;
  $("#user-name").textContent = user.username;
  $("#user-avatar").textContent = user.username.slice(0, 1).toUpperCase();
  $("#user-role").textContent = user.role === "admin" ? "Administrator" : "Staff";
  $("#accounts-nav").classList.toggle("hidden", user.role !== "admin");
}

function showApp() {
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
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
  if (!orders.length) return `<tr><td class="empty-state" colspan="5">មិនទាន់មានការលក់នៅឡើយទេ</td></tr>`;
  return orders.map((order) => {
    const itemText = order.items.map((item) => `${escapeHTML(item.name)} × ${item.quantity}`).join(", ");
    const date = new Date(`${order.created_at.replace(" ", "T")}Z`).toLocaleString("km-KH", { dateStyle: "medium", timeStyle: "short" });
    return `<tr><td><span class="product-name">${escapeHTML(order.order_number)}</span></td><td>${escapeHTML(order.customer_name || "អតិថិជនទូទៅ")}</td><td>${itemText}</td><td>${date}</td><td><b>${money(order.total)}</b></td></tr>`;
  }).join("");
}

async function loadDashboard() {
  const [metrics, productData, orderData] = await Promise.all([
    api("/api/dashboard"), api("/api/products"), api("/api/orders")
  ]);
  state.products = productData.products;
  state.orders = orderData.orders;
  $("#metric-revenue").textContent = money(metrics.today_revenue);
  $("#metric-orders").textContent = metrics.today_orders;
  $("#metric-products").textContent = metrics.active_products;
  $("#metric-low-stock").textContent = metrics.low_stock_products;
  $("#dashboard-products").innerHTML = productRows(state.products.slice(0, 5), true);
  $("#dashboard-orders").innerHTML = orderRows(state.orders.slice(0, 5), true);
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

async function loadAccounts() {
  const result = await api("/api/accounts");
  $("#accounts-table").innerHTML = result.accounts.map((account) => {
    const date = new Date(`${account.created_at.replace(" ", "T")}Z`).toLocaleString("km-KH", { dateStyle: "medium", timeStyle: "short" });
    const role = account.role === "admin" ? "អ្នកគ្រប់គ្រង" : "បុគ្គលិក";
    return `<tr><td><span class="product-name">${escapeHTML(account.username)}</span></td><td>${role}</td><td>${date}</td></tr>`;
  }).join("");
}

async function navigate(view) {
  if (view === "accounts" && state.user?.role !== "admin") {
    notify("មានតែអ្នកគ្រប់គ្រងប៉ុណ្ណោះដែលអាចគ្រប់គ្រងគណនីបាន");
    return;
  }
  state.activeView = view;
  document.querySelectorAll(".view").forEach((section) => section.classList.toggle("hidden", section.id !== `view-${view}`));
  document.querySelectorAll(".nav-link").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  try {
    if (view === "dashboard") await loadDashboard();
    if (view === "products") await loadProducts();
    if (view === "orders") await loadOrders();
    if (view === "accounts") await loadAccounts();
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

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  const form = new FormData(event.currentTarget);
  try {
    const result = await api("/api/login", { method: "POST", body: JSON.stringify({ username: form.get("username"), password: form.get("password") }) });
    setCurrentUser(result.user);
    showApp();
    $("#today-label").textContent = new Date().toLocaleDateString("km-KH", { dateStyle: "full" });
    await navigate("dashboard");
  } catch (error) { showError($("#login-error"), error); }
});

$("#logout-button").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (error) { notify(error.message); }
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
$("#add-account-button").addEventListener("click", () => {
  $("#account-form").reset();
  $("#account-form-error").textContent = "";
  $("#account-dialog").showModal();
});
$("#product-search").addEventListener("input", () => loadProducts().catch((error) => notify(error.message)));

$("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({
        username: form.elements.username.value,
        password: form.elements.password.value
      })
    });
    form.reset();
    $("#account-dialog").close();
    notify("បានបង្កើតគណនីបុគ្គលិករួចរាល់");
    await loadAccounts();
  } catch (error) {
    showError($("#account-form-error"), error);
  }
});

$("#product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const payload = {
    name: form.elements.name.value, sku: form.elements.sku.value,
    category: form.elements.category.value, price: Number(form.elements.price.value),
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

api("/api/me").then(async (result) => {
  setCurrentUser(result.user);
  showApp();
  $("#today-label").textContent = new Date().toLocaleDateString("km-KH", { dateStyle: "full" });
  await navigate("dashboard");
}).catch((error) => {
  if (!error.message.includes("ចូលគណនី")) {
    $("#login-form").elements.password.focus();
    notify(error.message);
  }
});
