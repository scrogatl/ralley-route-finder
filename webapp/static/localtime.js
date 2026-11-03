// Show each <time datetime="..."> in the viewer's own time zone, e.g.
// "Nov 3, 8:45 AM"; without JavaScript it keeps the UTC text the server wrote.
document.querySelectorAll('time[datetime]').forEach(el => {
  const when = new Date(el.getAttribute('datetime'));
  if (Number.isNaN(when.getTime())) return;
  el.textContent = when.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
  el.title = when.toLocaleString(undefined, {dateStyle: 'full', timeStyle: 'long'});
});
