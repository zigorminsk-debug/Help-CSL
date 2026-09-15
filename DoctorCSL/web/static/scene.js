/* Сцена Help CSL: офис, поездка, здание клиента. 25.12–14.01 — зима. */
(() => {
  const HOME = "home", WALK_OUT = "walk_out", DRIVE = "drive", ARRIVE = "arrive";
  const WORK = "work", LEAVE = "leave", RETURN = "return", WALK_IN = "walk_in";

  const PHASE = {
    dawn: ["rgba(255,150,90,0.28)", 0.28],
    day: ["rgba(255,230,180,0.08)", 0.08],
    dusk: ["rgba(230,90,40,0.32)", 0.32],
    night: ["rgba(10,18,50,0.42)", 0.42],
  };
  const HOLIDAY_PHASE = {
    dawn: ["rgba(180,200,230,0.08)", 0.08],
    day: ["rgba(210,226,240,0.04)", 0.04],
    dusk: ["rgba(70,90,150,0.08)", 0.08],
    night: ["rgba(8,16,42,0.10)", 0.10],
  };

  function dayPhase() {
    const hour = new Date().toLocaleString("en-GB", { timeZone: "Europe/Minsk", hour: "2-digit", hour12: false });
    const h = parseInt(hour, 10);
    if (h >= 5 && h < 8) return "dawn";
    if (h >= 8 && h < 17) return "day";
    if (h >= 17 && h < 21) return "dusk";
    return "night";
  }

  function isHolidaySeason() {
    const parts = new Date().toLocaleString("en-CA", { timeZone: "Europe/Minsk", year: "numeric", month: "2-digit", day: "2-digit" });
    const [, m, d] = parts.match(/(\d{4})-(\d{2})-(\d{2})/) || [];
    const month = Number(m), day = Number(d);
    return (month === 12 && day >= 25) || (month === 1 && day <= 14);
  }

  function loadImage(src) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  function cropOpaque(img) {
    if (!img) return null;
    const w = img.naturalWidth, h = img.naturalHeight;
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const g = c.getContext("2d");
    g.drawImage(img, 0, 0);
    const data = g.getImageData(0, 0, w, h).data;
    let x0 = w, y0 = h, x1 = 0, y1 = 0;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (data[(y * w + x) * 4 + 3] > 16) {
          if (x < x0) x0 = x;
          if (y < y0) y0 = y;
          if (x > x1) x1 = x;
          if (y > y1) y1 = y;
        }
      }
    }
    if (x1 <= x0) return img;
    const out = document.createElement("canvas");
    out.width = x1 - x0 + 1;
    out.height = y1 - y0 + 1;
    out.getContext("2d").drawImage(img, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
    return out;
  }

  function fit(img, maxW, maxH) {
    if (!img) return null;
    const w = img.width || img.naturalWidth;
    const h = img.height || img.naturalHeight;
    const k = Math.min(maxW / w, maxH / h, 1);
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w * k));
    c.height = Math.max(1, Math.round(h * k));
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c;
  }

  function mirror(img) {
    if (!img) return null;
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d");
    g.translate(c.width, 0);
    g.scale(-1, 1);
    g.drawImage(img, 0, 0);
    return c;
  }

  function isCslOrange(r, g, b, a) {
    return a > 180 && r > 190 && g >= 30 && g <= 150 && b < 90 && (r - g) > 90;
  }
  function isCslLetter(r, g, b, a) {
    return a > 160 && r > 220 && g > 200 && b > 180;
  }
  function mirrorKeepCsl(img) {
    const flipped = mirror(img);
    if (!flipped) return null;
    const w = img.width, h = img.height;
    if (w < 40 || h < 24) return flipped;
    const srcC = document.createElement("canvas");
    srcC.width = w; srcC.height = h;
    const sg = srcC.getContext("2d");
    sg.drawImage(img, 0, 0);
    const src = sg.getImageData(0, 0, w, h).data;
    const at = (data, x, y) => {
      const i = (y * w + x) * 4;
      return [data[i], data[i + 1], data[i + 2], data[i + 3]];
    };
    const panel = [];
    for (let y = (h * 0.12) | 0; y < Math.min(h, (h * 0.50) | 0); y++) {
      let left = -1, right = -1, n = 0;
      for (let x = 0; x < w; x++) {
        if (isCslOrange(...at(src, x, y))) {
          if (left < 0) left = x;
          right = x;
          n++;
        }
      }
      if (n < 12) continue;
      const span = right - left;
      if (span < w * 0.20 || span > w * 0.70) continue;
      panel.push([y, left, right]);
    }
    if (!panel.length) return flipped;
    const letters = [];
    for (const [y, left, right] of panel) {
      const inset = Math.max(2, ((right - left) / 8) | 0);
      for (let x = left + inset; x <= right - inset; x++) {
        if (isCslLetter(...at(src, x, y))) letters.push([x, y]);
      }
    }
    if (letters.length < 8) return flipped;
    let lx0 = w, ly0 = h, lx1 = 0, ly1 = 0;
    for (const [x, y] of letters) {
      if (x < lx0) lx0 = x;
      if (y < ly0) ly0 = y;
      if (x > lx1) lx1 = x;
      if (y > ly1) ly1 = y;
    }
    lx0 = Math.max(0, lx0 - 2);
    ly0 = Math.max(0, ly0 - 2);
    lx1 = Math.min(w, lx1 + 3);
    ly1 = Math.min(h, ly1 + 3);
    const fg = flipped.getContext("2d");
    const fd = fg.getImageData(0, 0, w, h);
    const fdata = fd.data;
    for (const [y, left, right] of panel) {
      const mleft = w - 1 - right, mright = w - 1 - left;
      let fr = 239, fgv = 91, fb = 21, fa = 255;
      for (let x = Math.max(0, mleft); x <= Math.min(w - 1, mright); x++) {
        const p = at(fdata, x, y);
        if (isCslOrange(...p)) { fr = p[0]; fgv = p[1]; fb = p[2]; fa = p[3]; break; }
      }
      const inset = Math.max(2, ((right - left) / 8) | 0);
      for (let x = mleft + inset; x <= mright - inset; x++) {
        if (x < 0 || x >= w) continue;
        const i = (y * w + x) * 4;
        const r = fdata[i], g = fdata[i + 1], b = fdata[i + 2], a = fdata[i + 3];
        if (isCslLetter(r, g, b, a) || (r > 200 && g > 150 && b > 100 && a > 160)) {
          fdata[i] = fr; fdata[i + 1] = fgv; fdata[i + 2] = fb; fdata[i + 3] = fa;
        }
      }
    }
    fg.putImageData(fd, 0, 0);
    const destX = w - lx1;
    if (destX < 0) return flipped;
    fg.save();
    fg.beginPath();
    for (const [x, y] of letters) {
      fg.rect(destX + (x - lx0) - 1, y - 1, 3, 3);
    }
    fg.clip();
    fg.drawImage(img, lx0, ly0, lx1 - lx0, ly1 - ly0, destX, ly0, lx1 - lx0, ly1 - ly0);
    fg.restore();
    return flipped;
  }

  class CityScene {
    constructor(canvas) {
      this.cv = canvas;
      this.ctx = canvas.getContext("2d");
      this.state = HOME;
      this.issueKey = "";
      this.clientName = "Клиент";
      this.cityX = 0;
      this.carX = 90;
      this.agentX = 28;
      this.facing = 1;
      this.tickn = 0;
      this.pendingEnter = false;
      this.speed = 1;
      this.replay = false;
      this.workTicks = 0;
      this.holidayForce = null;
      this.holiday = isHolidaySeason();
      this.mapsUrl = "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent("г. Минск, ул. Фабрициуса, 9");
      this.siteUrl = "https://csl.by";
      this.raw = {};
      this.city = this.carR = this.carL = this.agentR = this.agentL = this.tower = null;
      this.carW = 160; this.carH = 58;
      this.towerW = 70; this.towerH = 180;
      this.agentW = 28; this.agentH = 58;
      this.cityW = 800;
      this._last = 0;
      this.cv.addEventListener("click", (e) => this.onClick(e));
      window.addEventListener("resize", () => this.resize());
    }

    async boot() {
      const names = ["city.jpg", "winter.jpg", "ambulance_off.png", "tower.png", "agent.png", "santa.png", "sleigh.png"];
      const loaded = await Promise.all(names.map((n) => loadImage("/assets/" + n)));
      this.raw.city = loaded[0];
      this.raw.winter = loaded[1];
      this.raw.car = loaded[2];
      this.raw.tower = loaded[3];
      this.raw.agent = loaded[4];
      this.raw.santa = loaded[5];
      this.raw.sleigh = loaded[6];
      this.resize();
      requestAnimationFrame((t) => this.loop(t));
    }

    setHoliday(enabled) {
      this.holidayForce = enabled;
      this.holiday = enabled == null ? isHolidaySeason() : !!enabled;
      this.rebuild();
    }

    resize() {
      const parent = this.cv.parentElement;
      const cssH = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--scene")) || 200;
      const w = Math.max(320, parent ? parent.clientWidth : window.innerWidth);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      this.w = w;
      this.h = cssH;
      this.cv.width = Math.round(w * dpr);
      this.cv.height = Math.round(cssH * dpr);
      this.cv.style.width = w + "px";
      this.cv.style.height = cssH + "px";
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.rebuild();
    }

    rebuild() {
      this.holiday = this.holidayForce == null ? isHolidaySeason() : !!this.holidayForce;
      const fitH = Math.max(64, this.h - 2);
      const bg = this.holiday ? this.raw.winter : this.raw.city;
      if (bg) {
        const nw = Math.max(720, Math.round(bg.naturalWidth * fitH / Math.max(bg.naturalHeight, 1)));
        this.city = fit(bg, nw, fitH);
        this.cityW = this.city.width;
      }
      const vehSrc = this.holiday ? this.raw.sleigh : this.raw.car;
      if (vehSrc) {
        const cropped = this.holiday ? vehSrc : cropOpaque(vehSrc);
        const car = this.holiday
          ? fit(cropped, fitH * 1.65, fitH * 0.50)
          : fit(cropped, fitH * 1.15, fitH * 0.42);
        this.carR = car;
        this.carL = this.holiday ? mirror(car) : mirrorKeepCsl(car);
        this.carW = car.width;
        this.carH = car.height;
      }
      if (this.raw.tower) {
        const tw = fit(this.raw.tower, fitH * 0.72, fitH);
        this.tower = tw;
        this.towerW = tw.width;
        this.towerH = tw.height;
      }
      const personSrc = this.holiday ? this.raw.santa : this.raw.agent;
      if (personSrc) {
        const p = fit(personSrc, fitH * 0.28, fitH * 0.48);
        this.agentR = p;
        this.agentL = mirror(p);
        this.agentW = p.width;
        this.agentH = p.height;
      }
      if (this.state === HOME) {
        this.carX = this.towerW + 8;
        this.agentX = 16;
      }
    }

    towerWidth() { return Math.max(48, this.towerW || 70); }
    clientH() { return Math.max(70, Math.min(this.h - 6, this.towerH || this.h - 8)); }
    clientW() { return Math.max(120, Math.min(190, Math.round(this.clientH() * 0.78))); }
    clientX() { return Math.max(this.w - 8 - this.clientW(), this.w * 0.68); }
    parkX() { return Math.max(this.towerW + 24, this.clientX() - this.carW - 8); }
    doorX() { return this.clientX() + this.clientW() * 0.42; }
    moving() { return this.state === DRIVE || this.state === RETURN; }

    arm(key, name) {
      this.issueKey = key || this.issueKey;
      this.clientName = (name || "Клиент").slice(0, 18);
      this.pendingEnter = false;
    }
    stopReplay() {
      this.replay = false;
      this.speed = 1;
      this.workTicks = 0;
    }
    playReplay(key, name, speed) {
      this.replay = true;
      this.speed = Math.max(2, Math.min(16, Number(speed) || 8));
      this.workTicks = 0;
      this.playDepart(key, name);
    }
    playDepart(key, name) {
      if (!this.replay) {
        this.speed = 1;
        this.workTicks = 0;
      }
      this.arm(key, name);
      this.state = WALK_OUT;
      this.facing = 1;
      this.pendingEnter = true;
      this.agentX = 16;
      this.carX = this.towerW + 8;
    }
    playOnsite(key) {
      this.issueKey = key || this.issueKey;
      if ([ARRIVE, WORK, LEAVE].includes(this.state)) return;
      if ([WALK_OUT, DRIVE].includes(this.state)) { this.pendingEnter = true; return; }
      if (this.state === HOME) { this.playDepart(this.issueKey, this.clientName); return; }
      this.pendingEnter = true;
      this.state = ARRIVE;
      this.facing = 1;
    }
    playReturn(key) {
      if ([RETURN, WALK_IN, HOME, LEAVE].includes(this.state)) return;
      this.issueKey = key || this.issueKey;
      this.pendingEnter = false;
      if ([ARRIVE, WORK].includes(this.state)) {
        const inside = this.state === WORK || this.agentX >= this.doorX() - 1;
        this.state = LEAVE;
        this.facing = -1;
        if (inside) this.agentX = this.doorX();
      } else if (this.state === WALK_OUT) {
        this.state = WALK_IN;
        this.facing = -1;
      } else {
        this.state = RETURN;
        this.facing = -1;
      }
    }
    resetHome() {
      this.state = HOME;
      this.facing = 1;
      this.pendingEnter = false;
      this.carX = this.towerW + 8;
      this.agentX = 16;
      if (this.replay) this.stopReplay();
    }

    onClick(e) {
      const r = this.cv.getBoundingClientRect();
      const x = e.clientX - r.left;
      const ground = this.h - 4;
      if (x >= 0 && x <= this.towerW + 10) {
        window.open(this.mapsUrl, "_blank", "noopener");
        return;
      }
      window.open(this.siteUrl, "_blank", "noopener");
    }

    step() {
      this.tickn = (this.tickn + 1) % 40;
      const door = this.towerW + 8;
      const park = this.parkX();
      if (this.state === WALK_OUT) {
        this.facing = 1;
        const target = door + 6;
        this.agentX = Math.min(target, this.agentX + 2.4);
        if (this.agentX >= target - 0.5) {
          this.state = DRIVE;
          this.agentX = this.carX + 24;
        }
      } else if (this.state === DRIVE) {
        this.facing = 1;
        if (this.carX < park - 0.5) {
          this.cityX = (this.cityX + 4) % Math.max(this.cityW, 1);
          this.carX = Math.min(park, this.carX + 3.4);
        } else {
          this.carX = park;
          if (this.pendingEnter) {
            this.state = ARRIVE;
            this.facing = 1;
            this.agentX = this.carX + 22;
          }
        }
      } else if (this.state === ARRIVE) {
        this.facing = 1;
        this.carX = park;
        const target = this.doorX();
        if (this.agentX < target) this.agentX = Math.min(target, this.agentX + 2.8);
        else this.state = WORK;
      } else if (this.state === WORK) {
        this.carX = park;
        this.agentX = this.doorX();
      } else if (this.state === LEAVE) {
        this.facing = -1;
        this.carX = park;
        const doorCar = this.carX + 18;
        if (this.agentX > doorCar) this.agentX = Math.max(doorCar, this.agentX - 2.8);
        else { this.state = RETURN; this.facing = -1; }
      } else if (this.state === RETURN) {
        this.facing = -1;
        const cw = Math.max(this.cityW, 1);
        this.cityX = ((this.cityX - 4) % cw + cw) % cw;
        this.carX = Math.max(door, this.carX - 3.4);
        this.agentX = this.carX + 24;
        if (this.carX <= door + 1) {
          this.state = WALK_IN;
          this.facing = -1;
          this.agentX = door + 6;
        }
      } else if (this.state === WALK_IN) {
        this.facing = -1;
        this.agentX = Math.max(14, this.agentX - 2.4);
        if (this.agentX <= 16) this.resetHome();
      }
    }

    drawBuilding(ground) {
      const g = this.ctx;
      const x = this.clientX() | 0;
      const bw = this.clientW() | 0;
      const bh = this.clientH() | 0;
      const y0 = ground - bh;
      g.fillStyle = this.holiday ? "#1E3348" : "#2A3344";
      g.strokeStyle = "#F7631B";
      g.lineWidth = 2;
      g.fillRect(x, y0, bw, bh);
      g.strokeRect(x, y0, bw, bh);
      if (this.holiday) {
        g.fillStyle = "#E8EEF6";
        g.strokeStyle = "#C5D0DE";
        g.beginPath();
        g.moveTo(x - 4, y0 + 8);
        g.lineTo(x + bw / 2, y0 - 10);
        g.lineTo(x + bw + 4, y0 + 8);
        g.closePath();
        g.fill();
        g.stroke();
      }
      g.fillStyle = "#F7631B";
      g.fillRect(x + 6, y0 + 8, bw - 12, 36);
      g.fillStyle = "#fff";
      g.font = "bold 11px Segoe UI, sans-serif";
      g.textAlign = "center";
      g.fillText("Куда едем", x + bw / 2, y0 + 22);
      g.fillStyle = "#FFF4EA";
      g.fillText(this.clientName || "Клиент", x + bw / 2, y0 + 38);
      const rows = Math.max(3, Math.min(6, ((bh - 70) / 26) | 0));
      const cols = 3;
      const cellW = Math.max(16, ((bw - 28) / cols) | 0);
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const glow = (!this.holiday || (r + c + ((this.tickn / 8) | 0)) % 3)
            ? "#F4C56A" : "#7EC8FF";
          g.fillStyle = glow;
          g.fillRect(x + 12 + c * cellW, y0 + 54 + r * 26, cellW - 8, 14);
        }
      }
      g.fillStyle = "#1A1A1A";
      g.fillRect(x + ((bw / 2) | 0) - 14, ground - 32, 28, 32);
    }

    drawMoon() {
      const r = Math.max(10, Math.min(18, (this.h / 10) | 0));
      const cx = Math.max(80, this.w - 70);
      const cy = 8 + r;
      const g = this.ctx;
      g.fillStyle = "#E8EEF6";
      g.strokeStyle = "#D5DCE6";
      g.beginPath();
      g.arc(cx, cy, r, 0, Math.PI * 2);
      g.fill();
      g.stroke();
    }

    drawHeadlights(x, y) {
      if (this.holiday) return;
      const g = this.ctx;
      const beam = Math.max(28, this.carW * 0.34);
      const mid = y + this.carH * 0.60;
      const spread = Math.max(8, this.carH * 0.16);
      const inset = Math.max(4, this.carW * 0.03);
      const right = this.facing >= 0;
      const nose = right ? x + this.carW - inset : x + inset;
      const dir = right ? 1 : -1;
      g.beginPath();
      g.moveTo(nose, mid - 3);
      g.lineTo(nose + dir * beam, mid - spread);
      g.lineTo(nose + dir * (beam + 6), mid + spread + 4);
      g.lineTo(nose, mid + 7);
      g.closePath();
      g.fillStyle = "#FFF6C8";
      g.fill();
      g.beginPath();
      g.moveTo(nose, mid - 1);
      g.lineTo(nose + dir * beam * 0.62, mid - spread / 2);
      g.lineTo(nose + dir * beam * 0.62, mid + spread / 2 + 2);
      g.lineTo(nose, mid + 5);
      g.closePath();
      g.fillStyle = "#F6E39A";
      g.fill();
    }

    drawSnow() {
      const g = this.ctx;
      g.fillStyle = "#F4F8FC";
      for (let i = 0; i < 28; i++) {
        const sx = (i * 71 + (this.cityX | 0) * 2 + this.tickn * 3) % Math.max(this.w, 1);
        const sy = (i * 37 + this.tickn * 4) % Math.max(this.h, 1);
        const size = 1 + (i % 3);
        g.beginPath();
        g.arc(sx, sy, size, 0, Math.PI * 2);
        g.fill();
      }
    }

    draw() {
      const g = this.ctx;
      const w = this.w, h = this.h;
      g.clearRect(0, 0, w, h);
      g.fillStyle = "#0B1220";
      g.fillRect(0, 0, w, h);
      if (this.city) {
        const ox = -((this.cityX | 0) % this.cityW);
        g.drawImage(this.city, ox, 0);
        g.drawImage(this.city, ox + this.cityW, 0);
        const phase = dayPhase();
        const table = this.holiday ? HOLIDAY_PHASE : PHASE;
        g.fillStyle = (table[phase] || table.day)[0];
        g.fillRect(0, 0, w, h);
      }
      const ground = h - 4;
      if (this.tower) g.drawImage(this.tower, 2, ground - this.towerH);
      if ([DRIVE, ARRIVE, WORK, LEAVE, RETURN].includes(this.state)) this.drawBuilding(ground);
      const bounce = this.moving() && (((this.cityX | 0) / 5) | 0) % 2 === 0 ? 1 : 0;
      const carY = ground - this.carH - bounce;
      const carX = this.carX | 0;
      const car = this.facing >= 0 ? this.carR : this.carL;
      if (this.moving() && !this.holiday) this.drawHeadlights(carX, carY);
      if (car) g.drawImage(car, carX, carY);
      const show = [HOME, WALK_OUT, ARRIVE, LEAVE, WALK_IN].includes(this.state);
      const person = this.facing >= 0 ? this.agentR : this.agentL;
      if (show && person) g.drawImage(person, this.agentX | 0, ground - this.agentH);
      if (this.holiday) {
        this.drawMoon();
        this.drawSnow();
      }
    }

    loop(t) {
      const interval = this.state === HOME ? 50 : 33;
      if (!this._last || t - this._last >= interval) {
        this._last = t;
        if (this.state !== HOME) this.step();
        else this.tickn = (this.tickn + 1) % 40;
        this.draw();
      }
      requestAnimationFrame((n) => this.loop(n));
    }
  }

  window.CityScene = CityScene;
  window.SCENE_HOME = HOME;
  window.SCENE_RETURN = RETURN;
  window.SCENE_WALK_IN = WALK_IN;
})();
