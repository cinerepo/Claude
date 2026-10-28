// Popovers (details.actions/.filter-dropdown > .popover) live inside a <table>, and every
// <table> on this page has backdrop-filter set (the shared glass-panel look). That property
// forces the <table> to both (a) establish its own stacking context, so the popover's
// z-index can never out-rank a later sibling table's own separately-established context,
// and (b) establish a new containing block for position:fixed descendants, so switching the
// popover to fixed positioning in place still lands it relative to the table's own box
// instead of the viewport. Confirmed live via devtools against config.html's "IP inventory
// subnets" table sitting right after the device inventory table - a popover near the bottom
// of the inventory table rendered fully behind the subnets table and was not clickable.
//
// The only fix that escapes both problems: physically move the popover out from under the
// table (reparent it to <body>, which has neither property) the moment it opens, then
// position it with JS-computed viewport coordinates. Moved back to its original spot on
// close so the DOM stays clean across repeated opens of different rows.
//
// Also handles what plain <details> doesn't give you for free:
//   - True one-at-a-time accordion behavior, explicit rather than relying only on the
//     browser's native same-name exclusivity (belt-and-suspenders once reparenting is
//     involved).
//   - Closing on an outside click - <details> has no native "click outside to close".

function closeDetails(details) {
  if (!details.open) return;
  details.open = false; // triggers the 'toggle' handler below, which does the actual cleanup
}

document.addEventListener("toggle", function (e) {
  const details = e.target;
  if (details.tagName !== "DETAILS") return;
  const popover = details.querySelector(":scope > .popover") || details._popoverRef;
  if (!popover) return;

  if (!details.open) {
    if (popover._origParent) {
      popover._origParent.insertBefore(popover, popover._origNextSibling);
      popover._origParent = null;
      popover._origNextSibling = null;
    }
    popover.removeAttribute("style");
    details._popoverRef = null;
    return;
  }

  // Explicit accordion: close every other open actions/filter-dropdown, not just ones
  // sharing this one's `name` - two different `name` groups (e.g. row-actions vs a filter
  // dropdown) could otherwise both stay open at once.
  document.querySelectorAll("details.actions[open], details.filter-dropdown[open]").forEach(function (d) {
    if (d !== details) closeDetails(d);
  });

  details._popoverRef = popover; // for the close branch above, since after reparenting the
                                  // popover is no longer details' DOM child to query for.

  const rect = details.getBoundingClientRect();
  const width = popover.getBoundingClientRect().width;

  popover._origParent = popover.parentElement;
  popover._origNextSibling = popover.nextSibling;
  document.body.appendChild(popover);

  popover.style.position = "fixed";
  popover.style.width = width + "px";
  popover.style.top = (rect.bottom + 6) + "px";
  popover.style.zIndex = "999";
  if (details.classList.contains("actions")) {
    // Right-aligned to the trigger, same as the CSS default (details.actions .popover { right: 0 }).
    popover.style.left = "auto";
    popover.style.right = (window.innerWidth - rect.right) + "px";
  } else {
    // Left-aligned (filter dropdowns).
    popover.style.left = rect.left + "px";
    popover.style.right = "auto";
  }
}, true);

// Click outside an open popover (and outside its own trigger, which toggles natively)
// closes it. Not capture phase - let the click's own handler (e.g. a checkbox inside the
// popover) run first.
document.addEventListener("click", function (e) {
  document.querySelectorAll("details.actions[open], details.filter-dropdown[open]").forEach(function (details) {
    const popover = details._popoverRef || details.querySelector(":scope > .popover");
    const summary = details.querySelector(":scope > summary");
    if (popover && popover.contains(e.target)) return;
    if (summary && summary.contains(e.target)) return;
    closeDetails(details);
  });
});

// The popover is position:fixed (viewport-relative, computed once at open time) - scrolling
// the page moves the trigger row away from underneath it instead of the popover following
// along, which looks broken. Closing on scroll is the standard fix every popover library
// uses for this exact situation, rather than re-computing position on every scroll event.
window.addEventListener("scroll", function () {
  document.querySelectorAll("details.actions[open], details.filter-dropdown[open]").forEach(closeDetails);
}, true);
