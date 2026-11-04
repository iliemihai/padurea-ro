/* Eticheta de pe grafice și de pe harta județului: valoarea întâi, apoi ce e. Fără ea pagina e completă (tabelele au tot). */
(function () {
  var tip = document.createElement("div");
  tip.className = "tip"; tip.hidden = true; tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  function fill(el) {
    var v = document.createElement("b"), l = document.createElement("span");
    v.textContent = el.getAttribute("data-v") || "";
    l.textContent = el.getAttribute("data-l") || "";
    tip.replaceChildren(v, l);
    tip.hidden = false;
  }
  function place(x, y) {
    var w = tip.offsetWidth, h = tip.offsetHeight, vw = window.innerWidth;
    var left = Math.min(Math.max(8, x - w / 2), vw - w - 8), top = y - h - 12;
    if (top < 8) top = y + 16;
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hide() { tip.hidden = true; }
  document.querySelectorAll("[data-v]").forEach(function (el) {
    el.addEventListener("pointermove", function (ev) { fill(el); place(ev.clientX, ev.clientY); });
    el.addEventListener("pointerleave", hide);
    el.addEventListener("focus", function () { var r = el.getBoundingClientRect(); fill(el); place(r.left + r.width / 2, r.top); });
    el.addEventListener("blur", hide);
  });
  window.addEventListener("scroll", hide, { passive: true });
  /* pe telefon graficele se derulează în cutia lor: pornim de la lunile cele mai noi */
  document.querySelectorAll(".chartwrap").forEach(function (w) { w.scrollLeft = w.scrollWidth; });
})();
