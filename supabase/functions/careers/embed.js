/* OnPoint CRM careers widget. Add to a page:
 *   <div id="onpoint-jobs"></div>
 *   <script src="https://<project>.supabase.co/functions/v1/careers/embed.js" data-site="onpoint" async></script>
 * Optional: data-accent="#0b7a75" (button colour), data-target="onpoint-jobs" (the element id).
 * Works on single-page sites: it waits for the element to appear. */
(function () {
  var script = document.currentScript || document.querySelector('script[src*="/careers/embed.js"]');
  if (!script) return;
  var base = script.src.replace(/\/embed\.js(\?.*)?$/, "");
  var site = script.getAttribute("data-site") || "onpoint";
  var accent = script.getAttribute("data-accent") || "#0b7a75";
  var targetId = script.getAttribute("data-target") || "onpoint-jobs";
  var TYPE = { permanent: "Permanent", contract: "Contract", contract_to_hire: "Contract to hire", temporary: "Temporary" };
  var MODEL = { onsite: "On-site", hybrid: "Hybrid", remote: "Remote" };
  var listCache = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function inline(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  /* Small Markdown subset: headings, bullet and numbered lists, tables, paragraphs, bold, links. */
  function md(text) {
    var lines = String(text || "").replace(/\r/g, "").split("\n"), out = [], list = null, para = [], i = 0;
    function flushPara() { if (para.length) { out.push("<p>" + inline(para.join(" ")) + "</p>"); para = []; } }
    function flushList() { if (list) { out.push("</" + list + ">"); list = null; } }
    for (; i < lines.length; i++) {
      var l = lines[i], m;
      if (!l.trim()) { flushPara(); flushList(); continue; }
      if ((m = l.match(/^\s*(#{1,6})\s+(.*)$/))) {
        flushPara(); flushList();
        var lvl = Math.min(6, m[1].length + 2);
        out.push("<h" + lvl + ">" + inline(m[2].replace(/\*\*/g, "")) + "</h" + lvl + ">");
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l)) {
        flushPara(); flushList();
        var rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          if (!/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split("|"));
          i++;
        }
        i--;
        out.push("<table>" + rows.map(function (r) {
          return "<tr>" + r.map(function (c) { return "<td>" + inline(c.trim()) + "</td>"; }).join("") + "</tr>";
        }).join("") + "</table>");
        continue;
      }
      if ((m = l.match(/^\s*(?:[-*•●▪◦]|(\d+)[.)])\s+(.*)$/))) {
        flushPara();
        var kind = m[1] ? "ol" : "ul";
        if (list !== kind) { flushList(); out.push("<" + kind + ">"); list = kind; }
        out.push("<li>" + inline(m[2]) + "</li>");
        continue;
      }
      flushList();
      para.push(l.trim());
    }
    flushPara(); flushList();
    return out.join("\n");
  }
  function meta(j) {
    return [j.location, MODEL[j.work_model], TYPE[j.employment_type]].filter(Boolean).map(esc).join(" · ");
  }
  function posted(s) {
    if (!s) return "";
    var d = new Date(s), days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days < 1) return "Posted today";
    if (days < 2) return "Posted yesterday";
    if (days < 31) return "Posted " + days + " days ago";
    return "Posted " + d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }
  var VERSION = "2026-11-02.3";
  /* Never waits forever: gives up after 15 seconds with a reason the page can show. */
  function getJSON(path) {
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 15000);
    return fetch(base + path, ctrl ? { signal: ctrl.signal } : {}).then(function (r) {
      return r.text().then(function (t) {
        var b; try { b = JSON.parse(t); } catch (e) { b = null; }
        if (!r.ok) throw new Error((b && (b.error || b.message || b.msg)) || ("HTTP " + r.status));
        if (!b) throw new Error("The careers service sent an unexpected reply");
        return b;
      });
    }, function (e) {
      throw new Error(e && e.name === "AbortError" ? "The careers service didn’t answer within 15 seconds"
        : "Couldn’t reach the careers service (" + ((e && e.message) || "network error") + ")");
    }).then(function (b) { clearTimeout(timer); return b; }, function (e) {
      clearTimeout(timer);
      if (window.console) console.warn("[OnPoint careers " + VERSION + "] " + base + path + ": " + e.message);
      throw e;
    });
  }
  function css() {
    if (document.getElementById("opj-style")) return;
    var s = document.createElement("style");
    s.id = "opj-style";
    s.textContent = [
      ".opj{--opj-accent:" + accent + ";font:inherit;color:inherit;line-height:1.55;max-width:880px}",
      ".opj *{box-sizing:border-box}",
      ".opj-search{width:100%;padding:10px 12px;border:1px solid rgba(0,0,0,.2);border-radius:6px;font:inherit;margin:0 0 14px;background:#fff;color:#111}",
      ".opj-list{display:grid;gap:10px}",
      ".opj-card{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 18px;border:1px solid rgba(0,0,0,.12);border-radius:8px;background:rgba(255,255,255,.6);cursor:pointer;text-decoration:none;color:inherit}",
      ".opj-card:hover,.opj-card:focus-visible{border-color:var(--opj-accent);outline:none}",
      ".opj-title{font-weight:700;font-size:1.08em;margin:0}",
      ".opj-meta{opacity:.75;font-size:.92em;margin:2px 0 0}",
      ".opj-go{color:var(--opj-accent);font-weight:600;white-space:nowrap}",
      ".opj-back{background:none;border:0;padding:0;color:var(--opj-accent);font:inherit;font-weight:600;cursor:pointer;margin-bottom:14px}",
      ".opj-detail h2.opj-title{font-size:1.6em;margin:0 0 4px}",
      ".opj-desc{margin:18px 0 28px}.opj-desc h3,.opj-desc h4,.opj-desc h5{margin:1.2em 0 .4em}.opj-desc ul,.opj-desc ol{padding-left:1.3em}",
      ".opj-desc table{border-collapse:collapse;margin:8px 0}.opj-desc td{border:1px solid rgba(0,0,0,.15);padding:4px 8px;vertical-align:top}",
      ".opj-form{border:1px solid rgba(0,0,0,.12);border-radius:8px;padding:20px;background:rgba(255,255,255,.7)}",
      ".opj-form h3{margin:0 0 14px}",
      ".opj-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px 14px}",
      ".opj-field{display:flex;flex-direction:column;gap:4px;font-size:.92em;font-weight:600}",
      ".opj-field.wide{grid-column:1/-1}",
      ".opj-field input{font:inherit;font-weight:400;padding:9px 10px;border:1px solid rgba(0,0,0,.25);border-radius:6px;background:#fff;color:#111}",
      ".opj-opt{font-weight:400;opacity:.7}",
      ".opj-consent{font-size:.85em;opacity:.85;max-height:140px;overflow:auto;border:1px solid rgba(0,0,0,.1);border-radius:6px;padding:10px;margin:14px 0 8px;background:rgba(0,0,0,.02)}",
      ".opj-check{display:flex;gap:8px;align-items:flex-start;font-size:.92em}",
      ".opj-check input{margin-top:4px}",
      ".opj-btn{margin-top:16px;background:var(--opj-accent);color:#fff;border:0;border-radius:6px;padding:11px 22px;font:inherit;font-weight:700;cursor:pointer}",
      ".opj-btn[disabled]{opacity:.6;cursor:default}",
      ".opj-err{color:#b4412f;margin:10px 0 0;font-size:.92em}",
      ".opj-ok{padding:18px;border-radius:8px;background:rgba(11,122,117,.08);border:1px solid var(--opj-accent)}",
      ".opj-hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}",
      ".opj-muted{opacity:.7}.opj-small{font-size:.8em}",
      ".opj-general{border-style:dashed}.opj-after{margin-top:10px}",
      ".opj-badge{display:inline-block;font-size:.7em;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:var(--opj-accent);border:1px solid var(--opj-accent);border-radius:10px;padding:0 7px;margin-left:6px;vertical-align:middle}",
      ".opj-skills{border:1px solid rgba(0,0,0,.25);border-radius:6px;background:#fff;color:#111;padding:6px;font-weight:400}",
      ".opj-chips{display:flex;flex-wrap:wrap;gap:6px}.opj-chips:empty{display:none}.opj-chips:not(:empty){margin-bottom:6px}",
      ".opj-chip{display:inline-flex;align-items:center;gap:2px;background:rgba(11,122,117,.1);color:#063f3c;border-radius:12px;padding:2px 4px 2px 10px;font-size:.9em}",
      ".opj-chip button{background:none;border:0;font-size:1.1em;line-height:1;cursor:pointer;color:inherit;padding:0 5px}",
      ".opj-combo{position:relative}.opj-combo input{width:100%;border:0;outline:none;font:inherit;padding:4px;background:transparent;color:#111}",
      ".opj-options{position:absolute;z-index:20;left:-7px;right:-7px;top:calc(100% + 6px);max-height:260px;overflow:auto;margin:0;padding:4px 0;list-style:none;background:#fff;border:1px solid rgba(0,0,0,.2);border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.12)}",
      ".opj-options li[role=option]{padding:6px 12px;cursor:pointer}.opj-options li.on,.opj-options li[role=option]:hover{background:rgba(11,122,117,.1)}",
      ".opj-cat{padding:8px 12px 2px;font-size:.75em;font-weight:700;text-transform:uppercase;letter-spacing:.04em;opacity:.6}",
      ".opj-new{font-style:italic}",
      "@media (max-width:640px){.opj-grid{grid-template-columns:1fr}.opj-card{flex-direction:column;align-items:flex-start}}"
    ].join("\n");
    document.head.appendChild(s);
  }

  function start(root) {
    css();
    root.classList.add("opj");
    root.setAttribute("data-opj-version", VERSION);
    function route() {
      var m = location.hash.match(/^#job-([0-9a-f-]{36})$/i);
      if (m) showJob(m[1]);
      else if (location.hash === "#general-application") showGeneral();
      else showList();
    }
    function loadList() {
      if (listCache) return Promise.resolve(listCache);
      var q = "?site=" + encodeURIComponent(site);
      // Load the two separately, so the general application still shows if the jobs list fails (and vice versa).
      return Promise.all([
        getJSON("/jobs" + q).then(function (b) { return { jobs: b.jobs || [] }; }, function (e) { return { error: e.message }; }),
        getJSON("/general" + q).catch(function () { return { open: false }; })
      ]).then(function (r) {
        var out = { jobs: r[0].jobs || [], jobsError: r[0].error || null, general: r[1] };
        if (!out.jobsError) listCache = out;
        return out;
      });
    }
    function showList() {
      root.innerHTML = '<p class="opj-muted">Loading open roles…</p>';
      loadList().then(function (b) {
        var jobs = b.jobs, g = b.general || {};
        var generalCard = g.open ? '<a class="opj-card opj-general" href="#general-application"><div><p class="opj-title">' + esc(g.title) +
          ' <span class="opj-badge">Always open</span></p><p class="opj-meta">' + esc(g.intro) + '</p></div><span class="opj-go">Send your profile →</span></a>' : "";
        if (b.jobsError) {
          root.innerHTML = '<p class="opj-muted">Open roles couldn’t be loaded right now. Please refresh the page or try again later.</p>' +
            '<p class="opj-muted opj-small">Details: ' + esc(b.jobsError) + "</p>" +
            (generalCard ? '<div class="opj-list">' + generalCard + "</div>" : "");
          return;
        }
        if (!jobs.length) {
          root.innerHTML = '<p class="opj-muted">There are no open roles right now.' + (g.open ? "" : " Please check back soon.") + "</p>" +
            (generalCard ? '<div class="opj-list">' + generalCard + "</div>" : "");
          return;
        }
        root.innerHTML = (jobs.length > 6 ? '<input class="opj-search" type="search" placeholder="Search roles or locations" aria-label="Search roles">' : "") +
          '<div class="opj-list" role="list"></div>' + (generalCard ? '<div class="opj-list opj-after">' + generalCard + "</div>" : "");
        var listEl = root.querySelector(".opj-list"), search = root.querySelector(".opj-search");
        function draw(q) {
          var words = (q || "").toLowerCase().split(/\s+/).filter(Boolean);
          var shown = jobs.filter(function (j) {
            var hay = (j.title + " " + (j.location || "") + " " + (TYPE[j.employment_type] || "") + " " + (MODEL[j.work_model] || "")).toLowerCase();
            return words.every(function (w) { return hay.indexOf(w) >= 0; });
          });
          listEl.innerHTML = shown.map(function (j) {
            return '<a class="opj-card" role="listitem" href="#job-' + esc(j.id) + '"><div><p class="opj-title">' + esc(j.title) +
              '</p><p class="opj-meta">' + [meta(j), esc(posted(j.posted))].filter(Boolean).join(" · ") + '</p></div><span class="opj-go">View and apply →</span></a>';
          }).join("") || '<p class="opj-muted">No roles match your search.</p>';
        }
        draw("");
        if (search) search.addEventListener("input", function () { draw(search.value); });
      }).catch(function () {
        root.innerHTML = '<p class="opj-muted">Open roles couldn’t be loaded. Please refresh the page or try again later.</p>';
        if (window.console) console.error("[OnPoint careers " + VERSION + "] showing the list failed", arguments[0]);
      });
    }
    function back() {
      root.querySelector(".opj-back").addEventListener("click", function () { location.hash = ""; root.scrollIntoView({ behavior: "smooth" }); });
    }
    function formHtml(heading, consent, extra) {
      return '<form class="opj-form" novalidate><h3>' + heading + '</h3><div class="opj-grid">' +
        field("first_name", "First name", "text", true, "given-name") + field("last_name", "Last name", "text", true, "family-name") +
        field("email", "Email", "email", true, "email") + field("phone", "Phone", "tel", true, "tel") +
        field("linkedin", 'LinkedIn profile <span class="opj-opt">(optional)</span>', "url", false, "url", "https://www.linkedin.com/in/…", true) +
        (extra || "") +
        '<label class="opj-field wide"><span>Resume (PDF or Word, up to 10 MB)</span><input name="resume" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required></label>' +
        '</div><div class="opj-hp" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>' +
        '<div class="opj-consent">' + esc(consent.body || "") + "</div>" +
        '<label class="opj-check"><input type="checkbox" name="consent" required> <span>I have read and agree to the above.</span></label>' +
        '<button class="opj-btn" type="submit">Submit application</button><p class="opj-err" role="alert"></p></form>';
    }
    function wireForm(form, endpoint, fields, done, getSkills) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var err = form.querySelector(".opj-err"), btn = form.querySelector(".opj-btn");
        var problem = check(form);
        if (problem) { err.textContent = problem; return; }
        var data = new FormData(form);
        data.delete("skill_search");
        Object.keys(fields).forEach(function (k) { data.append(k, fields[k]); });
        (getSkills ? getSkills() : []).forEach(function (s) { data.append("skills", s); });
        btn.disabled = true; btn.textContent = "Sending…"; err.textContent = "";
        fetch(base + endpoint, { method: "POST", body: data }).then(function (r) {
          return r.json().then(function (b) { if (!r.ok || !b.ok) throw new Error(b.error || "Something went wrong"); });
        }).then(function () {
          form.outerHTML = '<div class="opj-ok" role="status">' + done + "</div>";
        }).catch(function (x) {
          err.textContent = x.message; btn.disabled = false; btn.textContent = "Submit application";
        });
      });
    }
    function showJob(id) {
      root.innerHTML = '<p class="opj-muted">Loading…</p>';
      getJSON("/jobs/" + id + "?site=" + encodeURIComponent(site)).then(function (b) {
        var j = b.job, consent = b.consent || {};
        root.innerHTML =
          '<div class="opj-detail"><button type="button" class="opj-back">← All open roles</button>' +
          '<h2 class="opj-title">' + esc(j.title) + '</h2><p class="opj-meta">' + [meta(j), esc(posted(j.posted))].filter(Boolean).join(" · ") + "</p>" +
          '<div class="opj-desc">' + md(j.description) + "</div>" + formHtml("Apply for this role", consent, skillsField()) + "</div>";
        back();
        var picker = skillPicker(root.querySelector(".opj-skills"), b.skills || []);
        wireForm(root.querySelector("form"), "/apply", { site: site, job_id: j.id, consent_version: consent.id || "" },
          "<strong>Thank you, your application has been sent.</strong><br>We’ve received your resume for " + esc(j.title) +
          ". If your background is a fit, we’ll be in touch.", picker.values);
        root.scrollIntoView({ behavior: "smooth", block: "start" });
      }).catch(function () {
        root.innerHTML = '<p class="opj-muted">This role is no longer open.</p><button type="button" class="opj-back">← All open roles</button>';
        back();
      });
    }
    function showGeneral() {
      root.innerHTML = '<p class="opj-muted">Loading…</p>';
      getJSON("/general?site=" + encodeURIComponent(site)).then(function (g) {
        if (!g.open) throw new Error("closed");
        var consent = g.consent || {};
        root.innerHTML = '<div class="opj-detail"><button type="button" class="opj-back">← All open roles</button>' +
          '<h2 class="opj-title">' + esc(g.title) + '</h2><div class="opj-desc"><p>' + esc(g.intro) + "</p></div>" +
          formHtml("Send us your profile", consent, skillsField()) + "</div>";
        back();
        var picker = skillPicker(root.querySelector(".opj-skills"), g.skills || []);
        wireForm(root.querySelector("form"), "/apply-general", { site: site, consent_version: consent.id || "" },
          "<strong>Thank you, your profile has been sent.</strong><br>We’ll be in touch when a role that fits your skills comes up.",
          picker.values);
        root.scrollIntoView({ behavior: "smooth", block: "start" });
      }).catch(function () {
        root.innerHTML = '<p class="opj-muted">We aren’t taking general applications right now.</p><button type="button" class="opj-back">← All open roles</button>';
        back();
      });
    }
    function skillsField() {
      return '<div class="opj-field wide"><span id="opj-skills-label">Your skills <span class="opj-opt">(pick from the list, or type your own and press Enter)</span></span>' +
        '<div class="opj-skills"><div class="opj-chips" aria-live="polite"></div>' +
        '<div class="opj-combo"><input name="skill_search" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="opj-skill-list" ' +
        'aria-labelledby="opj-skills-label" placeholder="e.g. Epic Beaker, HL7, project management" autocomplete="off" maxlength="60">' +
        '<ul class="opj-options" id="opj-skill-list" role="listbox" hidden></ul></div></div></div>';
    }
    /* Search-as-you-type skill picker: choose from the list (grouped by category) or add your own. */
    function skillPicker(box, catalog) {
      var chosen = [], input = box.querySelector("input"), list = box.querySelector(".opj-options"),
          chips = box.querySelector(".opj-chips"), active = -1, options = [];
      var lower = function (s) { return s.toLowerCase(); };
      function has(name) { return chosen.some(function (c) { return lower(c) === lower(name); }); }
      function drawChips() {
        chips.innerHTML = chosen.map(function (c, i) {
          return '<span class="opj-chip">' + esc(c) + '<button type="button" data-i="' + i + '" aria-label="Remove ' + esc(c) + '">×</button></span>';
        }).join("");
      }
      function add(name) {
        name = String(name || "").replace(/\s+/g, " ").trim().slice(0, 60);
        if (name.length < 2 || has(name) || chosen.length >= 40) return;
        var match = catalog.filter(function (k) { return lower(k.name) === lower(name); })[0];
        chosen.push(match ? match.name : name);
        drawChips(); input.value = ""; close(); input.focus();
      }
      function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; }
      function open() {
        var q = lower(input.value.trim()), words = q.split(/\s+/).filter(Boolean);
        var hits = catalog.filter(function (k) {
          var hay = lower(k.name + " " + k.category);
          return !has(k.name) && words.every(function (w) { return hay.indexOf(w) >= 0; });
        }).slice(0, q ? 12 : 60);
        options = hits.map(function (k) { return k.name; });
        var html = "", lastCat = null;
        hits.forEach(function (k, i) {
          if (k.category !== lastCat && !q) { html += '<li class="opj-cat" role="presentation">' + esc(k.category) + "</li>"; lastCat = k.category; }
          html += '<li role="option" id="opj-opt-' + i + '" data-i="' + i + '">' + esc(k.name) + "</li>";
        });
        var typed = input.value.replace(/\s+/g, " ").trim();
        if (typed.length >= 2 && !has(typed) && !hits.some(function (k) { return lower(k.name) === lower(typed); })) {
          options.push(typed);
          html += '<li role="option" class="opj-new" id="opj-opt-' + (options.length - 1) + '" data-i="' + (options.length - 1) + '">Add “' + esc(typed) + "”</li>";
        }
        list.innerHTML = html;
        list.hidden = !html; input.setAttribute("aria-expanded", html ? "true" : "false"); active = -1;
      }
      function highlight(i) {
        var els = list.querySelectorAll('[role="option"]');
        els.forEach(function (el) { el.classList.remove("on"); });
        if (els[i]) { els[i].classList.add("on"); els[i].scrollIntoView({ block: "nearest" }); input.setAttribute("aria-activedescendant", els[i].id); }
        active = i;
      }
      input.addEventListener("focus", open);
      input.addEventListener("input", open);
      input.addEventListener("keydown", function (e) {
        var n = list.querySelectorAll('[role="option"]').length;
        if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) open(); highlight(Math.min(n - 1, active + 1)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); highlight(Math.max(0, active - 1)); }
        else if (e.key === "Enter" || e.key === ",") {
          e.preventDefault();
          if (active >= 0 && options[active]) add(options[active]); else add(input.value);
        } else if (e.key === "Escape") close();
        else if (e.key === "Backspace" && !input.value && chosen.length) { chosen.pop(); drawChips(); }
      });
      list.addEventListener("mousedown", function (e) {
        var li = e.target.closest('[role="option"]');
        if (li) { e.preventDefault(); add(options[+li.getAttribute("data-i")]); }
      });
      input.addEventListener("blur", function () { setTimeout(close, 150); });
      chips.addEventListener("click", function (e) {
        var b = e.target.closest("button[data-i]");
        if (b) { chosen.splice(+b.getAttribute("data-i"), 1); drawChips(); input.focus(); }
      });
      return { values: function () { if (input.value.trim()) add(input.value); return chosen.slice(); } };
    }
    function field(name, label, type, req, ac, ph, wide) {
      return '<label class="opj-field' + (wide ? " wide" : "") + '"><span>' + label + '</span><input name="' + name + '" type="' + type + '"' +
        (req ? " required" : "") + ' autocomplete="' + ac + '"' + (ph ? ' placeholder="' + esc(ph) + '"' : "") + ' maxlength="300"></label>';
    }
    function check(form) {
      var v = function (n) { return (form.elements[n].value || "").trim(); };
      if (!v("first_name") || !v("last_name")) return "Please enter your first and last name.";
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v("email"))) return "Please enter a valid email address.";
      if ((v("phone").match(/\d/g) || []).length < 7) return "Please enter a phone number we can reach you on.";
      var f = form.elements.resume.files[0];
      if (!f) return "Please attach your resume.";
      if (!/\.(pdf|docx)$/i.test(f.name)) return "Please attach your resume as a PDF or Word (.docx) file.";
      if (f.size > 10 * 1024 * 1024) return "Your resume is larger than 10 MB. Please attach a smaller file.";
      if (!form.elements.consent.checked) return "Please tick the box to agree to how we use your information.";
      return "";
    }
    window.addEventListener("hashchange", route);
    route();
  }

  function mount() {
    var el = document.getElementById(targetId);
    if (el && !el.getAttribute("data-opj")) { el.setAttribute("data-opj", "1"); start(el); }
  }
  mount();
  new MutationObserver(mount).observe(document.documentElement, { childList: true, subtree: true });
})();
