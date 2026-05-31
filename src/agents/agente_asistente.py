import argparse
from decimal import Decimal
from uuid import uuid4

from flask import Flask, request as flask_request
from rdflib import Graph, Literal
from rdflib.namespace import RDF, RDFS

from utilities.builders import (
    build_devolucion_request,
    build_order_message,
    build_search_message,
    build_valoracion_request,
)
from utilities.comm import comm_url as _comm_url
from utilities.http import graph_from_request, post_graph, rdf_response
from utilities.acl import build_message, build_not_understood, correlate_reply, get_message
from utilities.namespaces import ACL, AGENTS, DATA, ECSDI, bind_namespaces
from utilities.runtime import (
    agent_address,
    agent_id,
    binding_from_args,
    configure_flask_logging,
    log,
    register_service,
    search_service,
    unregister_service,
)


DEFAULT_AGENT_URI = AGENTS.AsistenteVirtual

IFACE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ECSDI — Tienda</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #0e0e0e;
    --surface: #161616;
    --border: #2a2a2a;
    --accent: #c8f060;
    --accent2: #60c8f0;
    --text: #e8e8e0;
    --muted: #666;
    --danger: #f06060;
    --radius: 4px;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 13px;
    min-height: 100vh;
    padding: 0;
  }

  header {
    border-bottom: 1px solid var(--border);
    padding: 18px 40px;
    display: flex;
    align-items: baseline;
    gap: 20px;
  }

  header h1 {
    font-family: 'DM Serif Display', serif;
    font-size: 26px;
    letter-spacing: -0.5px;
    color: var(--accent);
  }

  header span {
    color: var(--muted);
    font-size: 11px;
  }

  nav {
    display: flex;
    gap: 2px;
    padding: 0 40px;
    border-bottom: 1px solid var(--border);
  }

  nav button {
    background: none;
    border: none;
    color: var(--muted);
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    padding: 12px 16px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.15s;
  }

  nav button.active, nav button:hover {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }

  .tab { display: none; padding: 32px 40px; }
  .tab.active { display: block; }

  .section-title {
    font-family: 'DM Serif Display', serif;
    font-size: 18px;
    margin-bottom: 24px;
    color: var(--text);
  }

  .form-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px;
    max-width: 860px;
  }

  .field { display: flex; flex-direction: column; gap: 6px; }
  .field.full { grid-column: 1 / -1; }

  label {
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
  }

  input, select {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 13px;
    padding: 9px 12px;
    border-radius: var(--radius);
    outline: none;
    transition: border-color 0.15s;
  }

  input:focus, select:focus { border-color: var(--accent); }

  .btn {
    background: var(--accent);
    color: #0e0e0e;
    border: none;
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    font-weight: 500;
    padding: 10px 22px;
    border-radius: var(--radius);
    cursor: pointer;
    letter-spacing: 0.5px;
    transition: opacity 0.15s;
    margin-top: 8px;
  }

  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn.secondary { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
  .btn.danger { background: var(--danger); }

  /* Resultados de búsqueda */
  #search-results { margin-top: 28px; max-width: 860px; }

  .product-list { display: flex; flex-direction: column; gap: 2px; }

  .product-row {
    display: grid;
    grid-template-columns: 1fr 100px 80px 120px 120px;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    cursor: pointer;
    transition: border-color 0.12s;
  }

  .product-row:hover, .product-row.selected {
    border-color: var(--accent);
  }

  .product-row.selected { background: #161f00; }

  .product-name { font-size: 13px; }
  .product-brand { color: var(--muted); font-size: 11px; }
  .product-badge {
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 99px;
    text-align: center;
  }
  .badge-interno { background: #1a2e00; color: var(--accent); }
  .badge-externo { background: #00212e; color: var(--accent2); }

  .product-price { text-align: right; color: var(--accent); }
  .product-rating { text-align: right; color: var(--muted); }

  .list-header {
    display: grid;
    grid-template-columns: 1fr 100px 80px 120px 120px;
    gap: 12px;
    padding: 6px 16px;
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 6px;
  }

  /* Pedido */
  #order-panel { max-width: 860px; }

  .selected-product-info {
    background: var(--surface);
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    padding: 14px 18px;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  /* Confirmación */
  #confirm-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    max-width: 600px;
    margin-top: 20px;
  }

  .confirm-row {
    display: flex;
    justify-content: space-between;
    padding: 7px 0;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
  }

  .confirm-row:last-child { border-bottom: none; }
  .confirm-key { color: var(--muted); }
  .confirm-val { color: var(--text); }
  .confirm-val.accent { color: var(--accent); }

  /* Feedback */
  .stars { display: flex; gap: 6px; margin: 8px 0; }
  .star {
    font-size: 22px;
    cursor: pointer;
    color: var(--border);
    transition: color 0.1s;
    user-select: none;
  }
  .star.active { color: var(--accent); }

  /* Estado / log */
  #status-bar {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    background: #0a0a0a;
    border-top: 1px solid var(--border);
    padding: 8px 40px;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 10px;
  }

  #status-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--muted);
    flex-shrink: 0;
  }

  #status-dot.ok { background: var(--accent); }
  #status-dot.loading {
    background: var(--accent2);
    animation: pulse 1s infinite;
  }
  #status-dot.error { background: var(--danger); }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  .empty-state {
    color: var(--muted);
    padding: 32px 0;
    font-size: 12px;
  }

  .rec-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 20px;
    align-items: center;
  }

  .rec-hint {
    color: var(--muted);
    font-size: 11px;
    flex: 1;
    min-width: 200px;
  }

  .rec-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 860px;
  }

  .rec-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 18px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 12px;
    align-items: start;
  }

  .rec-card.proactive { border-left: 3px solid var(--accent2); }
  .rec-card.on-demand { border-left: 3px solid var(--accent); }

  .rec-title { font-size: 14px; margin-bottom: 4px; }

  .rec-meta {
    color: var(--muted);
    font-size: 11px;
    line-height: 1.5;
  }

  .rec-score {
    font-size: 22px;
    color: var(--accent);
    text-align: right;
    line-height: 1;
  }

  .rec-score span {
    display: block;
    font-size: 9px;
    color: var(--muted);
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 4px;
  }

  .rec-actions {
    grid-column: 1 / -1;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 4px;
  }

  .nav-badge {
    display: inline-block;
    margin-left: 6px;
    padding: 1px 6px;
    font-size: 10px;
    background: var(--accent);
    color: #0e0e0e;
    border-radius: 10px;
    vertical-align: middle;
  }

  nav {
    overflow-x: auto;
    flex-wrap: nowrap;
  }

  pb-20 { padding-bottom: 20px; }
</style>
</head>
<body>

<header>
  <h1>ECSDI</h1>
  <span>Sistema de Comercio Electrónico Distribuido</span>
</header>

<nav>
  <button class="active" onclick="showTab('buscar', this)">01 / Buscar</button>
  <button onclick="showTab('pedido', this)">02 / Pedido</button>
  <button onclick="showTab('valoracion', this)">03 / Valoración</button>
  <button onclick="showTab('recomendaciones', this)">
    04 / Recomendaciones<span id="rec-badge" class="nav-badge" style="display:none">0</span>
  </button>
</nav>

<!-- TAB: BUSCAR -->
<div class="tab active" id="tab-buscar">
  <p class="section-title">Buscar productos</p>
  <div class="form-grid">
    <div class="field">
      <label>Nombre</label>
      <input id="s-name" type="text" placeholder="iPhone, batidora…">
    </div>
    <div class="field">
      <label>Marca</label>
      <input id="s-brand" type="text" placeholder="Apple, HomeUp…">
    </div>
    <div class="field">
      <label>Precio mín (€)</label>
      <input id="s-min-price" type="number" min="0" step="0.01" placeholder="0">
    </div>
    <div class="field">
      <label>Precio máx (€)</label>
      <input id="s-max-price" type="number" min="0" step="0.01" placeholder="sin límite">
    </div>
    <div class="field">
      <label>Valoración mín</label>
      <input id="s-min-rating" type="number" min="0" max="5" step="0.1" placeholder="0">
    </div>
  </div>
  <button class="btn" onclick="buscar()">Buscar →</button>

  <div id="search-results"></div>
</div>

<!-- TAB: PEDIDO -->
<div class="tab" id="tab-pedido">
  <p class="section-title">Realizar pedido</p>

  <div id="order-panel">
    <div id="selected-product-banner" style="display:none" class="selected-product-info">
      <div>
        <div id="sel-name" style="font-size:14px"></div>
        <div id="sel-price" style="color:var(--accent);margin-top:4px"></div>
      </div>
      <button class="btn secondary" onclick="showTab('buscar', document.querySelector('nav button'))">
        Cambiar producto
      </button>
      <button class="btn secondary" onclick="addSelectedToCart()">
        Añadir al carrito
      </button>
    </div>
    <div id="no-product-banner" class="empty-state">
      ← Selecciona primero un producto en la pestaña Buscar.
    </div>

    <div id="order-form" style="display:none">
      <div class="form-grid">
        <div class="field">
          <label>Ciudad</label>
          <input id="o-city" type="text" value="Barcelona">
        </div>
        <div class="field">
          <label>Calle</label>
          <input id="o-street" type="text" value="Carrer Mallorca 401">
        </div>
        <div class="field">
          <label>Código postal</label>
          <input id="o-postal" type="text" value="08013">
        </div>
        <div class="field">
          <label>País</label>
          <input id="o-country" type="text" value="España">
        </div>
        <div class="field">
          <label>Cantidad</label>
          <input id="o-qty" type="number" min="1" value="1">
        </div>
        <div class="field">
          <label>Prioridad envío</label>
          <select id="o-priority">
            <option value="1">1 — Urgente (1 día)</option>
            <option value="2">2 — Normal (3 días)</option>
            <option value="3" selected>3 — Económico (5 días)</option>
          </select>
        </div>
        <div class="field">
          <label>Método de pago</label>
          <select id="o-payment" onchange="toggleCardField()">
            <option value="tarjeta" selected>Tarjeta</option>
            <option value="paypal">PayPal</option>
            <option value="transferencia">Transferencia</option>
          </select>
        </div>
        <div class="field" id="card-field">
          <label>Número tarjeta</label>
          <input id="o-card" type="text" inputmode="numeric" autocomplete="cc-number" placeholder="4111111111111111">
        </div>
        <div class="field">
          <label>Distancia logística entrega (0–1000)</label>
          <input id="o-dist" type="number" min="0" max="1000" value="130">
        </div>
      </div>
      <div id="cart-box" style="margin-top:16px"></div>
      <button class="btn" onclick="hacerPedido()">Confirmar pedido →</button>
    </div>

    <div id="confirm-box" style="display:none"></div>
  </div>
</div>

<!-- TAB: VALORACIÓN -->
<div class="tab" id="tab-valoracion">
  <p class="section-title">Enviar valoración</p>
  <div class="form-grid">
    <div class="field">
      <label>ID Pedido</label>
      <input id="v-pedido" type="text" placeholder="PED-XXXXXXXX">
    </div>
    <div class="field">
      <label>ID Producto</label>
      <input id="v-product" type="text" placeholder="P-IPHONE19">
    </div>
    <div class="field full">
      <label>Puntuación</label>
      <div class="stars" id="stars">
        <span class="star" onclick="setStar(1)">★</span>
        <span class="star" onclick="setStar(2)">★</span>
        <span class="star" onclick="setStar(3)">★</span>
        <span class="star" onclick="setStar(4)">★</span>
        <span class="star" onclick="setStar(5)">★</span>
      </div>
    </div>
    <div class="field full">
      <label>Comentario</label>
      <input id="v-comment" type="text" placeholder="Muy buen producto…">
    </div>
  </div>
  <button class="btn" onclick="enviarValoracion()">Enviar valoración →</button>
  <button class="btn secondary" onclick="solicitarDevolucion()">Solicitar devolución</button>
  <div id="val-result" style="margin-top:16px;font-size:12px;color:var(--muted)"></div>
  <div id="return-result" style="margin-top:12px;font-size:12px;color:var(--muted)"></div>
  <div id="feedback-pending" style="margin-top:24px"></div>
</div>

<!-- TAB: RECOMENDACIONES -->
<div class="tab" id="tab-recomendaciones">
  <p class="section-title">Recomendaciones para ti</p>
  <div class="rec-toolbar">
    <button class="btn secondary" onclick="cargarRecomendacionesInbox()">Actualizar buzón</button>
    <button class="btn" onclick="pedirRecomendaciones()">Pedir ahora al feedback</button>
    <span class="rec-hint">
      El Agente Feedback envía sugerencias proactivas periódicamente (tras búsquedas/compras).
      También puedes solicitarlas al instante.
    </span>
  </div>
  <div id="rec-list" class="rec-list">
    <p class="empty-state">Pulsa «Actualizar buzón» o espera recomendaciones proactivas.</p>
  </div>
</div>

<div id="status-bar">
  <div id="status-dot"></div>
  <span id="status-msg">Listo</span>
</div>

<script>
  // ── Estado global ────────────────────────────────────────
  let selectedProduct = null;   // { id, name, price, uri, catalog_data }
  let cart = [];
  let lastPedidoId = '';
  let starRating = 0;
  let recPollTimer = null;
  let lastInboxCount = 0;

  // ── Estado bar ───────────────────────────────────────────
  function setStatus(msg, type = '') {
    document.getElementById('status-msg').textContent = msg;
    const dot = document.getElementById('status-dot');
    dot.className = type;
  }

  // ── Búsqueda ─────────────────────────────────────────────
  async function buscar() {
    const params = new URLSearchParams();
    const name = document.getElementById('s-name').value.trim();
    const brand = document.getElementById('s-brand').value.trim();
    const minP = document.getElementById('s-min-price').value;
    const maxP = document.getElementById('s-max-price').value;
    const minR = document.getElementById('s-min-rating').value;

    if (name) params.set('name', name);
    if (brand) params.set('brand', brand);
    if (minP) params.set('min_price', minP);
    if (maxP) params.set('max_price', maxP);
    if (minR) params.set('min_rating', minR);

    setStatus('Buscando…', 'loading');
    try {
      const res = await fetch('/search?' + params.toString());
      const data = await res.json();
      renderResults(data.products || [], data.error);
      setStatus(data.error ? data.error : `${(data.products||[]).length} producto(s) encontrado(s)`, data.error ? 'error' : 'ok');
    } catch (e) {
      setStatus('Error de conexión', 'error');
      document.getElementById('search-results').innerHTML = '<p class="empty-state">Error al conectar con el catálogo.</p>';
    }
  }

  function renderResults(products, error) {
    const el = document.getElementById('search-results');
    if (error) { el.innerHTML = `<p class="empty-state">${error}</p>`; return; }
    if (!products.length) { el.innerHTML = '<p class="empty-state">No se encontraron productos.</p>'; return; }

    const header = `<div class="list-header">
      <span>Producto</span><span>Marca</span><span>Tipo</span>
      <span style="text-align:right">Precio</span><span style="text-align:right">★ Rating</span>
    </div>`;

    const rows = products.map((p, i) => {
      const badge = p.type === 'interno'
        ? '<span class="product-badge badge-interno">interno</span>'
        : '<span class="product-badge badge-externo">externo</span>';
      return `<div class="product-row" id="prow-${i}" onclick="selectProduct(${i}, this)">
        <span class="product-name">${p.name}</span>
        <span class="product-brand">${p.brand}</span>
        ${badge}
        <span class="product-price">${parseFloat(p.price).toFixed(2)} €</span>
        <span class="product-rating">${parseFloat(p.rating).toFixed(2)}</span>
      </div>`;
    }).join('');

    el.innerHTML = header + '<div class="product-list">' + rows + '</div>';
    el._products = products;
  }

  function selectProduct(i, el) {
    document.querySelectorAll('.product-row').forEach(r => r.classList.remove('selected'));
    el.classList.add('selected');
    const products = document.getElementById('search-results')._products;
    selectedProduct = products[i];
    setStatus(`Seleccionado: ${selectedProduct.name}`, 'ok');
  }

  // ── Pedido ────────────────────────────────────────────────
  function showTab(name, btn) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    if (btn) btn.classList.add('active');

    if (recPollTimer) { clearInterval(recPollTimer); recPollTimer = null; }

    if (name === 'pedido') refreshOrderPanel();
    if (name === 'recomendaciones') {
      cargarRecomendacionesInbox();
      recPollTimer = setInterval(cargarRecomendacionesInbox, 15000);
    }
    if (name === 'valoracion') cargarFeedbackPendiente();
  }

  function refreshOrderPanel() {
    const banner = document.getElementById('selected-product-banner');
    const noBanner = document.getElementById('no-product-banner');
    const form = document.getElementById('order-form');
    const confirmBox = document.getElementById('confirm-box');

    if (selectedProduct) {
      banner.style.display = 'flex';
      noBanner.style.display = 'none';
      form.style.display = 'block';
      document.getElementById('sel-name').textContent = selectedProduct.name;
      document.getElementById('sel-price').textContent = parseFloat(selectedProduct.price).toFixed(2) + ' €';
    } else {
      banner.style.display = 'none';
      noBanner.style.display = 'block';
      form.style.display = 'none';
    }
    confirmBox.style.display = 'none';
    renderCart();
    toggleCardField();
  }

  function addSelectedToCart() {
    if (!selectedProduct) { setStatus('Selecciona un producto primero', 'error'); return; }
    const qty = parseInt(document.getElementById('o-qty').value) || 1;
    const existing = cart.find(item => item.id === selectedProduct.id);
    if (existing) {
      existing.quantity += qty;
    } else {
      cart.push({ ...selectedProduct, quantity: qty });
    }
    renderCart();
    setStatus(`${selectedProduct.name} añadido al carrito`, 'ok');
  }

  function removeCartItem(index) {
    cart.splice(index, 1);
    renderCart();
  }

  function renderCart() {
    const box = document.getElementById('cart-box');
    if (!box) return;
    if (!cart.length) {
      box.innerHTML = '<div class="empty-state" style="padding:8px 0">Carrito vacío: se pedirá el producto seleccionado.</div>';
      return;
    }
    box.innerHTML = '<div class="product-list">' + cart.map((item, i) =>
      `<div class="product-row" style="grid-template-columns:1fr 80px 100px 100px">
        <span class="product-name">${item.name}</span>
        <span>${item.quantity} ud.</span>
        <span class="product-price">${(parseFloat(item.price) * item.quantity).toFixed(2)} €</span>
        <button class="btn secondary" style="margin:0;padding:7px 10px" onclick="removeCartItem(${i})">Quitar</button>
      </div>`
    ).join('') + '</div>';
  }

  function toggleCardField() {
    const field = document.getElementById('card-field');
    const method = document.getElementById('o-payment');
    if (field && method) field.style.display = method.value === 'tarjeta' ? 'flex' : 'none';
  }

  async function hacerPedido() {
    if (!selectedProduct && !cart.length) { setStatus('Selecciona un producto primero', 'error'); return; }
    const items = cart.length ? cart : [{
      id: selectedProduct.id,
      price: selectedProduct.price,
      quantity: parseInt(document.getElementById('o-qty').value) || 1,
      name: selectedProduct.name,
    }];

    const body = {
      items: items.map(item => ({
        product_id: item.id,
        price: item.price,
        quantity: item.quantity,
        name: item.name,
      })),
      city: document.getElementById('o-city').value,
      street: document.getElementById('o-street').value,
      postal_code: document.getElementById('o-postal').value,
      country: document.getElementById('o-country').value,
      priority: parseInt(document.getElementById('o-priority').value),
      payment_method: document.getElementById('o-payment').value,
      payment_card: document.getElementById('o-card').value,
      delivery_dist: parseInt(document.getElementById('o-dist').value) || 0,
    };

    setStatus('Procesando pedido…', 'loading');
    try {
      const res = await fetch('/order', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
      const data = await res.json();
      if (data.error) { setStatus(data.error, 'error'); return; }
      renderConfirmation(data);
      setStatus('Pedido realizado correctamente', 'ok');
      lastPedidoId = data.pedido_id || '';
      cart = [];
      renderCart();
    } catch (e) {
      setStatus('Error al realizar el pedido', 'error');
    }
  }

  function renderConfirmation(data) {
    const box = document.getElementById('confirm-box');
    box.style.display = 'block';

    const row = (k, v, accent=false) =>
      `<div class="confirm-row"><span class="confirm-key">${k}</span><span class="confirm-val${accent?' accent':''}">${v}</span></div>`;

    let html = row('Pedido', data.pedido_id || '—')
      + row('Estado', data.estado || '—')
      + row('Factura', data.factura_id || '—')
      + row('Importe', (data.importe ? parseFloat(data.importe).toFixed(2) + ' €' : '—'), true);
    if (data.items && data.items.length) {
      html += row('Líneas', data.items.map(i => `${i.product_id} ×${i.quantity}`).join(', '));
    }

    if (data.envio_interno) {
      html += row('Envío', 'Interno — ' + (data.transportista || '').split('/').pop())
            + row('Entrega estimada', data.fecha_entrega || '—')
            + row('Coste envío', data.coste_envio ? parseFloat(data.coste_envio).toFixed(2) + ' €' : '—');
    } else if (data.envio_externo) {
      html += row('Envío', 'Externo — gestionado por el vendedor');
    }

    // Pre-rellenar pestaña valoración
    document.getElementById('v-pedido').value = data.pedido_id || '';
    document.getElementById('v-product').value = data.items && data.items.length ? data.items[0].product_id : (selectedProduct ? selectedProduct.id : '');

    box.innerHTML = html
      + `<button class="btn" style="margin-top:12px" onclick="showTab('valoracion', document.querySelectorAll('nav button')[2])">
           Valorar este producto →
         </button>`;
  }

  // ── Valoración ────────────────────────────────────────────
  function setStar(n) {
    starRating = n;
    document.querySelectorAll('.star').forEach((s, i) => {
      s.classList.toggle('active', i < n);
    });
  }

  async function enviarValoracion() {
    const pedido_id = document.getElementById('v-pedido').value.trim();
    const product_id = document.getElementById('v-product').value.trim();
    const comentario = document.getElementById('v-comment').value.trim();

    if (!pedido_id || !product_id) { setStatus('Rellena ID de pedido y producto', 'error'); return; }
    if (!starRating) { setStatus('Selecciona una puntuación', 'error'); return; }

    setStatus('Enviando valoración…', 'loading');
    try {
      const res = await fetch('/valoracion', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ pedido_id, product_id, puntuacion: starRating, comentario })
      });
      const data = await res.json();
      if (data.error) { setStatus(data.error, 'error'); document.getElementById('val-result').textContent = data.error; return; }
      setStatus('Valoración registrada', 'ok');
      document.getElementById('val-result').textContent = '✓ Valoración enviada correctamente.';
    } catch (e) {
      setStatus('Error al enviar valoración', 'error');
    }
  }

  async function solicitarDevolucion() {
    const pedido_id = document.getElementById('v-pedido').value.trim();
    const product_id = document.getElementById('v-product').value.trim();
    const motivo = document.getElementById('v-comment').value.trim() || 'Producto defectuoso';
    const box = document.getElementById('return-result');

    if (!pedido_id || !product_id) { setStatus('Rellena ID de pedido y producto', 'error'); return; }

    setStatus('Solicitando devolución…', 'loading');
    try {
      const res = await fetch('/devolucion', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ pedido_id, product_id, motivo })
      });
      const data = await res.json();
      if (data.error) { setStatus(data.error, 'error'); box.textContent = data.error; return; }
      setStatus(data.accepted ? 'Devolución aceptada' : 'Devolución denegada', data.accepted ? 'ok' : 'error');
      box.textContent = data.accepted
        ? `✓ Recogida: ${data.pickup || 'pendiente'} · Reembolso: ${data.refund_ref || 'sin referencia'}`
        : `Denegada: ${data.instructions || 'sin motivo'}`;
    } catch (e) {
      setStatus('Error al solicitar devolución', 'error');
    }
  }

  // ── Recomendaciones ───────────────────────────────────────
  function updateRecBadge(count) {
    const badge = document.getElementById('rec-badge');
    if (!badge) return;
    if (count > lastInboxCount) {
      badge.textContent = String(count);
      badge.style.display = 'inline-block';
    } else if (count === 0) {
      badge.style.display = 'none';
    }
    lastInboxCount = count;
  }

  function renderRecommendations(items) {
    const el = document.getElementById('rec-list');
    if (!items || !items.length) {
      el.innerHTML = '<p class="empty-state">Sin recomendaciones. Haz búsquedas o compras y vuelve más tarde, o pulsa «Pedir ahora».</p>';
      return;
    }

    el.innerHTML = items.map((r, i) => {
      const title = r.name || r.product_id || 'Producto';
      const sub = [r.brand, r.product_id, r.price ? `${parseFloat(r.price).toFixed(2)} €` : null]
        .filter(Boolean).join(' · ');
      const score = r.score ? parseFloat(r.score).toFixed(2) : '—';
      const reason = r.reason || 'Basado en tu historial de búsquedas y compras.';
      const date = r.date ? `<div class="rec-meta">Recibida: ${r.date}</div>` : '';
      const src = r.source === 'inbox' ? 'Proactiva (Agente Feedback)' : 'Bajo demanda';
      const cardClass = r.source === 'inbox' ? 'proactive' : 'on-demand';
      return `<div class="rec-card ${cardClass}">
        <div>
          <div class="rec-title">${title}</div>
          ${sub ? `<div class="rec-meta">${sub}</div>` : ''}
          <div class="rec-meta" style="margin-top:6px">${reason}</div>
          <div class="rec-meta">${src}</div>
          ${date}
          <div class="rec-actions">
            <button class="btn secondary" onclick="usarRecomendacion(${i})">Usar en pedido →</button>
          </div>
        </div>
        <div class="rec-score">${score}<span>puntos</span></div>
      </div>`;
    }).join('');
    el._items = items;
  }

  function usarRecomendacion(index) {
    const r = (document.getElementById('rec-list')._items || [])[index];
    if (!r || !r.product_id) { setStatus('Recomendación sin ID de producto', 'error'); return; }
    selectedProduct = {
      id: r.product_id,
      name: r.name || r.product_id,
      brand: r.brand || '',
      price: r.price || '0',
      rating: r.rating || '0',
      type: 'interno',
    };
    setStatus(`Producto ${selectedProduct.name} listo para pedir`, 'ok');
    showTab('pedido', document.querySelectorAll('nav button')[1]);
  }

  async function cargarRecomendacionesInbox() {
    try {
      const res = await fetch('/recommendations-inbox');
      const data = await res.json();
      const items = (data.inbox || []).map(r => ({ ...r, source: 'inbox' }));
      updateRecBadge(items.length);
      if (document.getElementById('tab-recomendaciones').classList.contains('active')) {
        renderRecommendations(items);
        lastInboxCount = items.length;
        const badge = document.getElementById('rec-badge');
        if (badge) badge.style.display = 'none';
      }
    } catch (e) {
      if (document.getElementById('tab-recomendaciones').classList.contains('active')) {
        document.getElementById('rec-list').innerHTML = '<p class="empty-state">No se pudo leer el buzón.</p>';
      }
    }
  }

  async function pedirRecomendaciones() {
    setStatus('Solicitando recomendaciones…', 'loading');
    try {
      const res = await fetch('/recommendations');
      const data = await res.json();
      if (data.error) {
        setStatus(data.error, 'error');
        document.getElementById('rec-list').innerHTML = `<p class="empty-state">${data.error}</p>`;
        return;
      }
      const items = (data.recommendations || []).map(r => ({ ...r, source: 'on_demand' }));
      renderRecommendations(items);
      setStatus(`${items.length} recomendación(es)`, items.length ? 'ok' : '');
    } catch (e) {
      setStatus('Error al contactar con feedback', 'error');
    }
  }

  async function cargarFeedbackPendiente() {
    const box = document.getElementById('feedback-pending');
    if (!box) return;
    try {
      const res = await fetch('/feedback-requests');
      const data = await res.json();
      const reqs = data.requests || [];
      if (!reqs.length) { box.innerHTML = ''; return; }
      const last = reqs[reqs.length - 1];
      box.innerHTML = `<div class="selected-product-info" style="border-color:var(--accent2)">
        <div>
          <div style="font-size:12px;color:var(--accent2)">PedirFeedback pendiente</div>
          <div style="margin-top:6px">Pedido <strong>${last.pedido_id}</strong> · Producto <strong>${last.product_id}</strong></div>
        </div>
        <button class="btn secondary" onclick="document.getElementById('v-pedido').value='${last.pedido_id}';document.getElementById('v-product').value='${last.product_id}'">
          Rellenar formulario
        </button>
      </div>`;
    } catch (e) {
      box.innerHTML = '';
    }
  }

  // ── Init ─────────────────────────────────────────────────
  setStatus('Listo', 'ok');
  cargarRecomendacionesInbox();
</script>
</body>
</html>
"""


def create_app(
    agent_uri=DEFAULT_AGENT_URI,
    catalog_url="http://127.0.0.1:9006/comm",
    shop_url="http://127.0.0.1:9001/comm",
    feedback_url="http://127.0.0.1:9007/comm",
    devolucion_url="http://127.0.0.1:9009/comm",
):
    app = Flask(__name__)
    app._feedback_requests = []
    app._recommendations_inbox: list[dict] = []

    # ── /iface ────────────────────────────────────────────────────────────────

    @app.get("/iface")
    def iface():
        return IFACE_HTML, 200, {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        }

    @app.get("/")
    def index():
        return "AsistenteVirtualAgent listo — accede a /iface para la interfaz web"

    # ── API interna (llamada desde el JS del /iface) ───────────────────────────

    @app.get("/search")
    def search():
        """Búsqueda de productos. Llama al AgenteCatalogo y devuelve JSON."""
        import json
        name = flask_request.args.get("name")
        brand = flask_request.args.get("brand")
        min_price = flask_request.args.get("min_price")
        max_price = flask_request.args.get("max_price")
        min_rating = flask_request.args.get("min_rating")

        constraints = {}
        if name:       constraints["name"]       = name
        if brand:      constraints["brand"]      = brand
        if min_price:  constraints["min_price"]  = Decimal(min_price)
        if max_price:  constraints["max_price"]  = Decimal(max_price)
        if min_rating: constraints["min_rating"] = Decimal(min_rating)

        if not constraints:
            return app.response_class(
                json.dumps({"error": "Introduce al menos un criterio de búsqueda."}),
                mimetype="application/json"
            )

        try:
            search_message = build_search_message(
                sender=agent_uri,
                receiver=AGENTS.AgenteCatalogo,
                constraints=constraints,
            )
            response = post_graph(catalog_url, search_message)
        except Exception as exc:
            return app.response_class(
                json.dumps({"error": f"No se pudo contactar con el catálogo: {exc}"}),
                mimetype="application/json"
            )
        failure = _acl_failure_payload(response, "Catálogo rechazó la búsqueda")
        if failure is not None:
            return app.response_class(json.dumps(failure), mimetype="application/json")

        from utilities.namespaces import ECSDI as _ECSDI
        products = []
        for product in response.objects(None, _ECSDI.resultadoContieneProducto):
            pid   = str(next(response.objects(product, _ECSDI.idProducto), ""))
            name_ = str(next(response.objects(product, _ECSDI.nombreProducto), ""))
            brand_= str(next(response.objects(product, _ECSDI.marcaProducto), ""))
            price = str(next(response.objects(product, _ECSDI.precioProducto), "0"))
            rating= str(next(response.objects(product, _ECSDI.valoracionMedia), "0"))
            is_ext= (product, RDF.type, _ECSDI.ProductoExterno) in response
            products.append({
                "id": pid,
                "name": name_,
                "brand": brand_,
                "price": price,
                "rating": rating,
                "uri": str(product),
                "type": "externo" if is_ext else "interno",
            })

        # Guardamos el grafo de catálogo en la sesión de la app para el pedido
        app._last_search_graph = response
        cache = getattr(app, "_catalog_cache_graph", Graph())
        bind_namespaces(cache)
        for triple in response:
            cache.add(triple)
        app._catalog_cache_graph = cache

        return app.response_class(
            json.dumps({"products": products}),
            mimetype="application/json"
        )

    @app.post("/order")
    def order():
        """Realiza un pedido. Llama al AgenteComerciante y devuelve JSON."""
        import json
        data = flask_request.get_json(force=True)

        raw_items = data.get("items") or []
        if raw_items:
            product_quantities = {
                str(item.get("product_id")): int(item.get("quantity", 1))
                for item in raw_items
                if item.get("product_id")
            }
            product_prices = {
                str(item.get("product_id")): Decimal(str(item.get("price", "0")))
                for item in raw_items
                if item.get("product_id")
            }
        else:
            product_id = data.get("product_id")
            product_quantities = {product_id: int(data.get("quantity", 1))} if product_id else {}
            product_prices = {product_id: Decimal(str(data.get("price", "0")))} if product_id else {}
        city       = data.get("city", "")
        street     = data.get("street", "")
        postal_code= data.get("postal_code", "")
        country    = data.get("country", "")
        priority   = int(data.get("priority", 3))
        payment_method = _payment_label(data.get("payment_method", "tarjeta"), data.get("payment_card", ""))
        delivery_dist = int(data.get("delivery_dist", 130))
        if not product_quantities:
            return app.response_class(
                json.dumps({"error": "Selecciona al menos un producto."}),
                mimetype="application/json"
            )

        catalog_graph = getattr(app, "_catalog_cache_graph", None) or getattr(app, "_last_search_graph", None)

        try:
            order_message = build_order_message(
                sender=agent_uri,
                receiver=AGENTS.AgenteComerciante,
                product_quantities=product_quantities,
                product_prices=product_prices,
                city=city,
                street=street,
                postal_code=postal_code,
                country=country,
                priority=priority,
                payment_method=payment_method,
                delivery_dist=delivery_dist,
                catalog_graph=catalog_graph,
            )
            order_response = post_graph(shop_url, order_message)
        except Exception as exc:
            return app.response_class(
                json.dumps({"error": f"No se pudo contactar con el comerciante: {exc}"}),
                mimetype="application/json"
            )
        failure = _acl_failure_payload(order_response, "Comerciante rechazó el pedido")
        if failure is not None:
            return app.response_class(json.dumps(failure), mimetype="application/json")

        from utilities.namespaces import ECSDI as _ECSDI
        pedido = next(order_response.subjects(RDF.type, _ECSDI.Pedido), None)
        factura = next(order_response.subjects(RDF.type, _ECSDI.Factura), None)

        result = {
            "pedido_id":  str(next(order_response.objects(pedido, _ECSDI.idPedido), "")),
            "estado":     str(next(order_response.objects(pedido, _ECSDI.estadoPedido), "")),
            "factura_id": str(next(order_response.objects(factura, _ECSDI.idFactura), "")),
            "importe":    str(next(order_response.objects(factura, _ECSDI.importeFactura), "0")),
            "envio_interno": False,
            "envio_externo": False,
            "items": [
                {"product_id": pid, "quantity": qty}
                for pid, qty in product_quantities.items()
            ],
        }

        confirmacion = next(order_response.objects(pedido, _ECSDI.pedidoTieneConfirmacion), None)
        if confirmacion:
            envio = next(order_response.objects(confirmacion, _ECSDI.confirmacionEnvio), None)
            transportista = next(order_response.objects(envio, _ECSDI.envioRealizadoPor), None) if envio else None
            oferta = next(order_response.subjects(RDF.type, _ECSDI.OfertaTransporte), None)
            fecha = next(order_response.objects(oferta, _ECSDI.fechaEntregaEstimada), None) if oferta else None
            precio_envio = next(order_response.objects(oferta, _ECSDI.precioOferta), None) if oferta else None
            result.update({
                "envio_interno": True,
                "transportista": str(transportista) if transportista else "",
                "fecha_entrega": str(fecha) if fecha else "",
                "coste_envio":   str(precio_envio) if precio_envio else "",
            })
        else:
            envio_ext = next(order_response.objects(pedido, _ECSDI.pedidoTieneEnvio), None)
            if envio_ext:
                result["envio_externo"] = True

        return app.response_class(json.dumps(result), mimetype="application/json")

    @app.post("/valoracion")
    def valoracion():
        """Envía una valoración al AgenteFeedback."""
        import json
        data = flask_request.get_json(force=True)

        pedido_id  = data.get("pedido_id", "")
        product_id = data.get("product_id", "")
        puntuacion = int(data.get("puntuacion", 0))
        comentario = data.get("comentario", "")

        if not (1 <= puntuacion <= 5):
            return app.response_class(
                json.dumps({"error": "Puntuación debe estar entre 1 y 5"}),
                mimetype="application/json"
            )

        try:
            val_message = build_valoracion_request(
                sender=agent_uri,
                receiver=AGENTS.AgenteFeedback,
                pedido_id=pedido_id,
                product_id=product_id,
                puntuacion=puntuacion,
                comentario=comentario,
            )
            response = post_graph(feedback_url, val_message)
            failure = _acl_failure_payload(response, "Feedback rechazó la valoración")
            if failure is not None:
                return app.response_class(
                    json.dumps(failure),
                    mimetype="application/json"
                )
        except Exception as exc:
            return app.response_class(
                json.dumps({"error": f"No se pudo contactar con feedback: {exc}"}),
                mimetype="application/json"
            )

        return app.response_class(
            json.dumps({"ok": True}),
            mimetype="application/json"
        )

    @app.post("/devolucion")
    def devolucion():
        """Solicita una devolución al AgenteDevolucion."""
        import json
        data = flask_request.get_json(force=True)
        pedido_id = data.get("pedido_id", "")
        product_id = data.get("product_id", "")
        motivo = data.get("motivo", "Producto defectuoso")

        if not pedido_id or not product_id:
            return app.response_class(
                json.dumps({"error": "Rellena ID de pedido y producto"}),
                mimetype="application/json"
            )

        try:
            response = post_graph(
                devolucion_url,
                build_devolucion_request(
                    sender=agent_uri,
                    receiver=AGENTS.AgenteDevolucion,
                    pedido_id=pedido_id,
                    product_id=product_id,
                    motivo=motivo,
                ),
            )
        except Exception as exc:
            return app.response_class(
                json.dumps({"error": f"No se pudo contactar con devolución: {exc}"}),
                mimetype="application/json"
            )
        failure = _acl_failure_payload(response, "Devolución rechazó la solicitud")
        if failure is not None:
            return app.response_class(json.dumps(failure), mimetype="application/json")

        devolucion_node = next(response.subjects(RDF.type, ECSDI.Devolucion), None)
        reembolso = next(response.objects(devolucion_node, ECSDI.devolucionTieneReembolso), None) if devolucion_node else None
        accepted_raw = str(next(response.objects(devolucion_node, ECSDI.devolucionAceptada), "false")).lower() if devolucion_node else "false"
        result = {
            "accepted": accepted_raw in ("true", "1"),
            "instructions": str(next(response.objects(devolucion_node, ECSDI.instruccionesDevolucion), "")) if devolucion_node else "",
            "pickup": str(next(response.objects(devolucion_node, ECSDI.fechaRecogidaDevolucion), "")) if devolucion_node else "",
            "refund_ref": str(next(response.objects(reembolso, ECSDI.referenciaPago), "")) if reembolso else "",
        }
        return app.response_class(json.dumps(result), mimetype="application/json")

    @app.get("/feedback-requests")
    def feedback_requests():
        import json
        return app.response_class(
            json.dumps({"requests": getattr(app, "_feedback_requests", [])}),
            mimetype="application/json"
        )

    @app.get("/recommendations-inbox")
    def recommendations_inbox():
        """Buzón de recomendaciones recibidas como ACL.inform desde el AgenteFeedback."""

        import json
        return app.response_class(
            json.dumps({"inbox": getattr(app, "_recommendations_inbox", [])}),
            mimetype="application/json",
        )

    @app.get("/recommendations")
    def recommendations():
        import json
        graph = Graph()
        bind_namespaces(graph)
        action = DATA[f"action/recomendaciones/{uuid4()}"]
        graph.add((action, RDF.type, ECSDI.BuscarProductos))
        graph.add((action, ECSDI.tipoBusqueda, Literal("recomendacion")))
        message = build_message(graph, action, ACL.request, agent_uri, AGENTS.AgenteFeedback)
        try:
            response = post_graph(feedback_url, message)
        except Exception as exc:
            return app.response_class(
                json.dumps({"error": f"No se pudo contactar con feedback: {exc}"}),
                mimetype="application/json"
            )
        failure = _acl_failure_payload(response, "Feedback rechazó la recomendación")
        if failure is not None:
            return app.response_class(json.dumps(failure), mimetype="application/json")

        items = []
        for rec in response.subjects(RDF.type, ECSDI.Recomendacion):
            product = next(response.objects(rec, ECSDI.recomendacionDeProducto), None)
            items.append({
                "product_id": str(next(response.objects(product, ECSDI.idProducto), "")) if product else "",
                "name": str(next(response.objects(product, ECSDI.nombreProducto), "")) if product else "",
                "brand": str(next(response.objects(product, ECSDI.marcaProducto), "")) if product else "",
                "price": str(next(response.objects(product, ECSDI.precioProducto), "")) if product else "",
                "rating": str(next(response.objects(product, ECSDI.valoracionMedia), "")) if product else "",
                "score": str(next(response.objects(rec, ECSDI.puntosRecomendacion), "")),
                "reason": str(next(response.objects(rec, ECSDI.motivoRecomendacion), "")),
            })
        return app.response_class(json.dumps({"recommendations": items}), mimetype="application/json")

    # ── /comm — endpoint ACL (para que otros agentes puedan contactarnos) ─────

    @app.post("/comm")
    def comm():
        try:
            graph = graph_from_request()
            message = get_message(graph)
            if message is None or message.content is None:
                return rdf_response(
                    build_not_understood(agent_uri, AGENTS.AgenteComerciante, "Mensaje ACL no reconocido")
                )
            def reply(response_graph: Graph):
                return rdf_response(correlate_reply(response_graph, message))
            action = message.content
            if message.performative == ACL.request and (action, RDF.type, ECSDI.PedirFeedback) in graph:
                pedido = next(graph.objects(action, ECSDI.accionSobrePedido), None)
                product = next(graph.objects(action, ECSDI.accionSobreProducto), None)
                app._feedback_requests.append({
                    "pedido_id": str(next(graph.objects(pedido, ECSDI.idPedido), "")) if pedido else "",
                    "product_id": str(next(graph.objects(product, ECSDI.idProducto), "")) if product else "",
                    "from": str(message.sender),
                })
                log("asistente", f"PedirFeedback recibido: pedido={pedido} producto={product}")
                return reply(build_message(graph, action, ACL.inform, agent_uri, message.sender))

            # Recomendación proactiva (cap. 9): el agente feedback envía
            # ACL.inform con un grafo de Recomendaciones cada T minutos. El
            # asistente las almacena en su inbox para que el usuario las
            # consulte por /recommendations-inbox.
            if message.performative == ACL.inform and any(graph.subjects(RDF.type, ECSDI.Recomendacion)):
                for rec in graph.subjects(RDF.type, ECSDI.Recomendacion):
                    product = next(graph.objects(rec, ECSDI.recomendacionDeProducto), None)
                    app._recommendations_inbox.append(
                        {
                            "product_id": str(next(graph.objects(product, ECSDI.idProducto), "")) if product else "",
                            "name": str(next(graph.objects(product, ECSDI.nombreProducto), "")) if product else "",
                            "brand": str(next(graph.objects(product, ECSDI.marcaProducto), "")) if product else "",
                            "price": str(next(graph.objects(product, ECSDI.precioProducto), "")) if product else "",
                            "rating": str(next(graph.objects(product, ECSDI.valoracionMedia), "")) if product else "",
                            "score": str(next(graph.objects(rec, ECSDI.puntosRecomendacion), "")),
                            "reason": str(next(graph.objects(rec, ECSDI.motivoRecomendacion), "")),
                            "date": str(next(graph.objects(rec, ECSDI.fechaRecomendacion), "")),
                            "from": str(message.sender),
                        }
                    )
                log("asistente", f"Recomendaciones proactivas recibidas: {len(app._recommendations_inbox)} en inbox")
                return reply(build_message(graph, action, ACL.inform, agent_uri, message.sender))

            return reply(build_not_understood(agent_uri, message.sender, "El AsistenteVirtual no acepta requests externos"))
        except Exception as exc:
            from utilities.acl import build_failure
            return rdf_response(build_failure(agent_uri, AGENTS.AgenteComerciante, None, str(exc)), status=500)

    return app


def _payment_label(method: str, card_number: str) -> str:
    method = (method or "tarjeta").strip()
    if method != "tarjeta":
        return method
    digits = "".join(ch for ch in str(card_number) if ch.isdigit())
    if len(digits) >= 4:
        return f"tarjeta ****{digits[-4:]}"
    return method


def _acl_failure_payload(response: Graph, default_reason: str) -> dict | None:
    msg = get_message(response)
    if msg is None or msg.performative != ACL.failure:
        return None
    reason = str(next(response.objects(None, RDFS.comment), "")) or default_reason
    return {"error": reason}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--hostaddr", default=None)
    parser.add_argument("--open", action="store_true", default=False)
    parser.add_argument("--port", type=int, default=9010)
    parser.add_argument("--dir", default=None, help="URL del servicio de directorio")
    parser.add_argument("--catalog-url", default=None)
    parser.add_argument("--shop-url", default=None)
    parser.add_argument("--feedback-url", default=None)
    parser.add_argument("--devolucion-url", default=None)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()

    configure_flask_logging(args.verbose)

    bind_host, advertised_host = binding_from_args(args.open, args.host, args.hostaddr)
    address = agent_address(advertised_host, args.port)
    service_id = agent_id("AGENTE_ASISTENTE", advertised_host, args.port)

    # Descubrir servicios via directorio o usar defaults
    catalog_base  = args.catalog_url  or search_service(args.dir, "AGENTE_CATALOGO", service_id)   or "http://127.0.0.1:9006"
    shop_base     = args.shop_url     or search_service(args.dir, "AGENTE_COMERCIANTE", service_id) or "http://127.0.0.1:9001"
    feedback_base = args.feedback_url or search_service(args.dir, "AGENTE_FEEDBACK", service_id)   or "http://127.0.0.1:9007"
    devolucion_base = args.devolucion_url or search_service(args.dir, "AGENTE_DEVOLUCION", service_id) or "http://127.0.0.1:9009"

    catalog_url  = _comm_url(catalog_base)
    shop_url     = _comm_url(shop_base)
    feedback_url = _comm_url(feedback_base)
    devolucion_url = _comm_url(devolucion_base)

    registered = register_service(
        args.dir,
        service_id,
        "AGENTE_ASISTENTE",
        address,
        f"asistente-{args.port}",
        capabilities=[ECSDI.PedirFeedback],
    )

    try:
        log(
            f"asistente-{args.port}",
            f"listening on {bind_host}:{args.port} | "
            f"catalog={catalog_url} shop={shop_url} feedback={feedback_url} devolucion={devolucion_url} | "
            f"iface → http://{advertised_host}:{args.port}/iface"
        )
        create_app(
            catalog_url=catalog_url,
            shop_url=shop_url,
            feedback_url=feedback_url,
            devolucion_url=devolucion_url,
        ).run(host=bind_host, port=args.port, debug=False, use_reloader=False)
    finally:
        if registered:
            unregister_service(args.dir, service_id, f"asistente-{args.port}")


if __name__ == "__main__":
    main()
