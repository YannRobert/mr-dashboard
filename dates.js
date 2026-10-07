// Date et heure affichées par toutes les pages du dashboard, quelle que soit la langue : jour, mois, année,
// du plus utile au moins utile, mois sur deux chiffres. Jamais le format américain du navigateur.
window.formatDateTime = iso => {
  const date = new Date(iso);
  const two = n => String(n).padStart(2, "0");
  return `${two(date.getDate())}/${two(date.getMonth() + 1)}/${date.getFullYear()} ${two(date.getHours())}:${two(date.getMinutes())}`;
};
