document.querySelectorAll("[data-faq-toggle]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const item = btn.closest(".landing-faq-item");
    const wasOpen = item.classList.contains("open");
    document.querySelectorAll(".landing-faq-item.open").forEach((el) => el.classList.remove("open"));
    if (!wasOpen) item.classList.add("open");
  });
});

const navToggle = document.querySelector("[data-nav-toggle]");
const navLinks = document.querySelector(".landing-nav-links");
if (navToggle && navLinks) {
  navToggle.addEventListener("click", () => {
    const isOpen = navLinks.style.display === "flex";
    navLinks.style.display = isOpen ? "none" : "flex";
    navLinks.style.flexDirection = "column";
    navLinks.style.position = "absolute";
    navLinks.style.top = "64px";
    navLinks.style.left = "0";
    navLinks.style.right = "0";
    navLinks.style.padding = "20px 24px";
    navLinks.style.background = "rgba(9,11,16,.97)";
    navLinks.style.borderBottom = "1px solid var(--line)";
  });
}

const revealTargets = document.querySelectorAll("[data-reveal]");
if ("IntersectionObserver" in window && revealTargets.length) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("in-view");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });
  revealTargets.forEach((target) => observer.observe(target));
} else {
  revealTargets.forEach((target) => target.classList.add("in-view"));
}
