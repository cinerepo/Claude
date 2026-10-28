function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = el.scrollHeight + "px";
}
document.addEventListener("input", function (e) {
  if (e.target.tagName === "TEXTAREA") autoGrow(e.target);
});
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("textarea").forEach(autoGrow);
});
