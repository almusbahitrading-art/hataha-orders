const INK = "#17181f", RED = "#c5102a", MUT = "#6b6357", LINE = "#e3d6c1";
const F = (w, s, fam) => `${w} ${s}px ${fam || "Tajawal"}, Tahoma, sans-serif`;

async function drawCard(c, D, logoUrl) {
  const x = c.getContext("2d");
  try { await Promise.all([document.fonts.load(F(700, 38)), document.fonts.load(F(400, 60, "Lalezar"))]); } catch (e) {}
  const logo = new Image(); logo.src = logoUrl; await logo.decode();
  x.direction = "rtl";
  x.fillStyle = "#f4ecdf"; x.fillRect(0, 0, 1080, 1350);
  x.fillStyle = "#fff"; x.strokeStyle = LINE; x.lineWidth = 2; x.beginPath(); x.roundRect(50, 50, 980, 1250, 24); x.fill(); x.stroke();
  const lw = 440; x.drawImage(logo, 320, 90, lw, logo.height * lw / logo.width);
  for (let px = 50 + (980 % 48) / 2; px + 48 <= 1030; px += 48) {   // شريط النقش
    x.fillStyle = INK; x.beginPath(); x.moveTo(px, 357); x.lineTo(px + 24, 345); x.lineTo(px + 48, 357); x.lineTo(px + 24, 369); x.fill();
    x.fillStyle = RED; x.beginPath(); x.moveTo(px + 15, 357); x.lineTo(px + 24, 352); x.lineTo(px + 33, 357); x.lineTo(px + 24, 362); x.fill();
  }
  x.textAlign = "center"; x.fillStyle = INK; x.font = F(400, 64, "Lalezar"); x.fillText(D.title, 540, 470);
  x.font = F(700, 36); x.fillText(D.sub, 540, 525);
  if (D.cancelled) {
    x.fillStyle = RED; x.font = F(700, 46); x.fillText("تم إلغاء هذا الطلب", 540, 760);
    x.fillStyle = MUT; x.font = F(500, 34); x.fillText("للاستفسار تواصل معنا على واتساب", 540, 830);
  } else {
    const Y = i => 610 + i * 80, last = D.steps.length - 1, fin = D.i === last;
    x.lineWidth = 5;
    for (let i = 0; i < last; i++) { x.strokeStyle = (i < D.i) ? INK : LINE; x.beginPath(); x.moveTo(900, Y(i)); x.lineTo(900, Y(i + 1)); x.stroke(); }
    D.steps.forEach((s, i) => {
      const y = Y(i), done = i < D.i || fin, now = i === D.i && !fin;
      if (now) { x.fillStyle = "rgba(197,16,42,.18)"; x.beginPath(); x.arc(900, y, 32, 0, 7); x.fill(); }
      x.beginPath(); x.arc(900, y, now ? 20 : 16, 0, 7); x.fillStyle = done ? INK : now ? RED : "#fff"; x.fill();
      if (!done && !now) { x.strokeStyle = LINE; x.lineWidth = 4; x.stroke(); }
      if (done) { x.strokeStyle = "#fff"; x.lineWidth = 4; x.beginPath(); x.moveTo(892, y); x.lineTo(898, y + 7); x.lineTo(909, y - 7); x.stroke(); }
      x.textAlign = "right"; x.fillStyle = (done || now) ? INK : MUT; x.font = F(now ? 700 : 500, now ? 42 : 36); x.fillText(s, 850, y + 13);
    });
  }
  x.textAlign = "center"; x.fillStyle = RED; x.font = F(400, 44, "Lalezar"); x.fillText("اطلبها .. نوصلها لك", 540, 1195);
  x.fillStyle = MUT; x.font = F(500, 28); x.fillText("آخر تحديث: \u2066" + D.date + "\u2069", 540, 1250);
}

async function initCard(c, D, logoUrl, ui) {   // رسم البطاقة + ربط زر النسخ والتحميل
  await drawCard(c, D, logoUrl);
  ui.dl.href = c.toDataURL("image/png");
  ui.copy.onclick = () => c.toBlob(async b => {
    try { await navigator.clipboard.write([new ClipboardItem({"image/png": b})]); ui.msg.textContent = "تم نسخ الصورة. الصقها في واتساب بـ Ctrl+V."; }
    catch (e) { ui.msg.textContent = "المتصفح لم يسمح بالنسخ. استخدم زر التحميل ثم أرفق الصورة من الجهاز."; }
  });
}
