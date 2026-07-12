(async function () {
  const statusLine = document.getElementById('status-line');
  const competitionSelect = document.getElementById('competition-select');
  const homeSelect = document.getElementById('home-select');
  const awaySelect = document.getElementById('away-select');
  const predictBtn = document.getElementById('predict-btn');
  const resultPanel = document.getElementById('result-panel');

  let seasonData = null;
  let manifest = null;

  try {
    const res = await fetch('data/manifest.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    manifest = await res.json();
  } catch (err) {
    statusLine.textContent = 'Could not load data/manifest.json. Run sync-all and redeploy.';
    predictBtn.disabled = true;
    return;
  }

  if (!manifest.competitions || manifest.competitions.length === 0) {
    statusLine.textContent = 'No competitions available yet — add an API key or CSV data and re-run sync-all.';
    predictBtn.disabled = true;
    return;
  }

  manifest.competitions.forEach((c) => {
    const opt = document.createElement('option');
    opt.value = c.file;
    opt.textContent = c.name;
    competitionSelect.appendChild(opt);
  });

  function statusForLoadedData() {
    const asOf = seasonData.generated_at_last_match
      ? new Date(seasonData.generated_at_last_match).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
      : 'unknown';
    return `${seasonData.teams.length} teams loaded · ${seasonData.competition} · data through ${asOf}`;
  }

  async function loadCompetition(file) {
    predictBtn.disabled = true;
    statusLine.textContent = 'Loading competition data…';
    resultPanel.classList.add('hidden');
    try {
      const res = await fetch(file, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      seasonData = await res.json();
    } catch (err) {
      statusLine.textContent = `Could not load ${file}.`;
      predictBtn.disabled = true;
      return;
    }

    populateSelect(homeSelect, seasonData.teams);
    populateSelect(awaySelect, seasonData.teams);
    if (seasonData.teams.length > 1) awaySelect.selectedIndex = 1;

    statusLine.textContent = statusForLoadedData();
    predictBtn.disabled = false;
  }

  competitionSelect.addEventListener('change', () => loadCompetition(competitionSelect.value));
  await loadCompetition(manifest.competitions[0].file);

  document.getElementById('swap-btn').addEventListener('click', () => {
    const homeVal = homeSelect.value;
    homeSelect.value = awaySelect.value;
    awaySelect.value = homeVal;
  });

  predictBtn.addEventListener('click', () => {
    const homeTeam = seasonData.teams.find((t) => t.id === homeSelect.value);
    const awayTeam = seasonData.teams.find((t) => t.id === awaySelect.value);

    if (homeTeam.id === awayTeam.id) {
      statusLine.textContent = 'Pick two different teams.';
      return;
    }

    predictBtn.disabled = true;
    predictBtn.textContent = 'Simulating 10,000 matches…';

    // setTimeout so the button label actually paints before the sim blocks the thread
    setTimeout(() => {
      const prediction = predictMatch(homeTeam, awayTeam, seasonData.league_avg_goals);
      renderResult(prediction, homeTeam, awayTeam);
      predictBtn.disabled = false;
      predictBtn.textContent = 'Get Prediction';
      statusLine.textContent = statusForLoadedData();
      resultPanel.classList.remove('hidden');
      resultPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 30);
  });

  function populateSelect(select, teams) {
    select.innerHTML = '';
    teams.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = t.name;
      select.appendChild(opt);
    });
  }

  function renderResult(pred, homeTeam, awayTeam) {
    document.getElementById('scoreline-big').textContent =
      `${homeTeam.name} ${pred.mostLikelyScoreline.replace('-', ' – ')} ${awayTeam.name}`;
    document.getElementById('xg-line').textContent =
      `Expected goals: ${pred.expectedGoals.home} — ${pred.expectedGoals.away}`;

    document.getElementById('pct-home').textContent = pctLabel(pred.outcomeProbabilities.home);
    document.getElementById('pct-draw').textContent = pctLabel(pred.outcomeProbabilities.draw);
    document.getElementById('pct-away').textContent = pctLabel(pred.outcomeProbabilities.away);
    document.getElementById('confidence-val').textContent = pred.confidence.toFixed(2);

    drawGauge(pred.outcomeProbabilities);

    document.getElementById('explanation-text').textContent = pred.explanation;

    const factorsList = document.getElementById('factors-list');
    factorsList.innerHTML = '';
    pred.topFactors.forEach((f) => {
      const li = document.createElement('li');
      const favoredName = f.favors === 'home' ? homeTeam.name : f.favors === 'away' ? awayTeam.name : 'neither side';
      li.innerHTML = `<b>${f.factor}</b> — favors ${favoredName} (magnitude ${f.magnitude})`;
      factorsList.appendChild(li);
    });

    fillTable('scorelines-table', pred.topScorelines.map((s) => [s.score, pctLabel(s.probability)]));
    fillTable('markets-table', [
      ['BTTS', pctLabel(pred.markets.bttsProbability)],
      ['Over 2.5', pctLabel(pred.markets.over25Probability)],
      ['Under 2.5', pctLabel(pred.markets.under25Probability)],
      [`${homeTeam.name} clean sheet`, pctLabel(pred.markets.homeCleanSheetProbability)],
      [`${awayTeam.name} clean sheet`, pctLabel(pred.markets.awayCleanSheetProbability)],
    ]);
    fillTable('first-scorer-table', pred.goalscorers.firstGoalscorerTop3.map((s) => [s.player, pctLabel(s.firstGoalscorerProbability)]));
    fillTable('anytime-table', [
      ...pred.goalscorers.homeAnytimeScorers.map((s) => [s.player, pctLabel(s.anytimeScorerProbability)]),
      ...pred.goalscorers.awayAnytimeScorers.map((s) => [s.player, pctLabel(s.anytimeScorerProbability)]),
    ]);
  }

  function pctLabel(x) {
    return `${Math.round(x * 100)}%`;
  }

  function fillTable(id, rows) {
    const table = document.getElementById(id);
    table.innerHTML = '';
    rows.forEach(([label, value]) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
      table.appendChild(tr);
    });
  }

  /* Signature element: a floodlight-style semicircular gauge split into
     home/draw/away arcs, echoing the stadium-lights motif from the masthead. */
  function drawGauge(probs) {
    const svg = document.getElementById('gauge-svg');
    const cx = 150, cy = 150, r = 120, strokeWidth = 26;
    const circumference = Math.PI * r; // semicircle length

    const segments = [
      { key: 'home', value: probs.home, color: '#1B4332' },
      { key: 'draw', value: probs.draw, color: '#E8A33D' },
      { key: 'away', value: probs.away, color: '#3A6EA5' },
    ];

    let offset = 0;
    let paths = '';
    segments.forEach((seg) => {
      const len = seg.value * circumference;
      paths += `<path d="M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}"
        fill="none" stroke="${seg.color}" stroke-width="${strokeWidth}"
        stroke-dasharray="${len} ${circumference}" stroke-dashoffset="${-offset}"
        stroke-linecap="butt" />`;
      offset += len;
    });

    const needleAngle = Math.PI * (1 - (probs.home + probs.draw / 2));
    const needleX = cx + (r - strokeWidth / 2) * Math.cos(needleAngle);
    const needleY = cy - (r - strokeWidth / 2) * Math.sin(needleAngle);

    svg.innerHTML = `
      <g>${paths}</g>
      <circle cx="${cx}" cy="${cy}" r="5" fill="#17201C" />
      <line x1="${cx}" y1="${cy}" x2="${needleX}" y2="${needleY}" stroke="#17201C" stroke-width="2.5" stroke-linecap="round" />
    `;
  }
})();
