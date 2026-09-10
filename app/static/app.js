document.addEventListener("DOMContentLoaded", () => {
  const labelSelect = document.querySelector("[data-label-select]");
  const featureOptions = document.querySelectorAll("[data-feature-option]");
  if (!labelSelect || !featureOptions.length) return;

  const syncLabel = () => {
    featureOptions.forEach((option) => {
      const input = option.querySelector("input");
      const isLabel = option.dataset.columnName === labelSelect.value;
      input.disabled = isLabel;
      input.checked = isLabel ? false : input.checked;
      option.classList.toggle("is-disabled", isLabel);
    });
  };
  labelSelect.addEventListener("change", syncLabel);
  syncLabel();
});
