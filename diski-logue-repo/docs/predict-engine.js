/* Diski Logue — client-side prediction engine
   Direct JS port of models/{team_strength,form_model,goals_model,scorer_model,ensemble}.py
   and explain/explainer.py. Runs entirely in the browser — the "live" part
   of "pick a fixture, get a live prediction": every prediction here is
   computed fresh, on demand, from the pre-aggregated season stats. */

const WEIGHTS = { strength: 30, form: 25, goals: 10 };
const HOME_ADVANTAGE_ELO = 60;
const HOME_ADVANTAGE_GOALS = 1.12;

function expectedScore(a, b) {
  return 1 / (1 + Math.pow(10, (b - a) / 400));
}

function strengthProbs(homeElo, awayElo) {
  const expHome = expectedScore(homeElo + HOME_ADVANTAGE_ELO, awayElo);
  const ratingGap = Math.abs(homeElo + HOME_ADVANTAGE_ELO - awayElo);
  const draw = Math.max(0.18, 0.30 - ratingGap / 1000);
  const home = expHome * (1 - draw);
  const away = (1 - expHome) * (1 - draw);
  const total = home + draw + away;
  return { home: home / total, draw: draw / total, away: away / total };
}

function formProbs(homeForm, awayForm) {
  const ppgGap = homeForm.ppg - awayForm.ppg;
  const homeEdge = 1 / (1 + Math.exp(-ppgGap));
  const draw = Math.max(0.20, 0.32 - Math.abs(ppgGap) * 0.05);
  const home = homeEdge * (1 - draw);
  const away = (1 - homeEdge) * (1 - draw);
  const total = home + draw + away;
  return { home: home / total, draw: draw / total, away: away / total };
}

function expectedGoals(homeTeam, awayTeam, leagueAvg) {
  const homeLambda = leagueAvg * homeTeam.attack * awayTeam.defense * HOME_ADVANTAGE_GOALS;
  const awayLambda = leagueAvg * awayTeam.attack * homeTeam.defense;
  return [Math.max(0.15, homeLambda), Math.max(0.15, awayLambda)];
}

// Knuth's Poisson sampler — matches the Python implementation
function poissonSample(lambda) {
  const L = Math.exp(-lambda);
  let k = 0, p = 1;
  do {
    k++;
    p *= Math.random();
  } while (p > L);
  return k - 1;
}

function monteCarloSimulation(homeLambda, awayLambda, nRuns = 10000) {
  const scorelineCounts = new Map();
  let btts = 0, over25 = 0, homeCS = 0, awayCS = 0;
  let homeWins = 0, draws = 0, awayWins = 0;

  for (let i = 0; i < nRuns; i++) {
    const hg = poissonSample(homeLambda);
    const ag = poissonSample(awayLambda);
    const key = `${hg}-${ag}`;
    scorelineCounts.set(key, (scorelineCounts.get(key) || 0) + 1);

    if (hg > 0 && ag > 0) btts++;
    if (hg + ag > 2.5) over25++;
    if (ag === 0) homeCS++;
    if (hg === 0) awayCS++;
    if (hg > ag) homeWins++;
    else if (hg < ag) awayWins++;
    else draws++;
  }

  const topScorelines = [...scorelineCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([score, count]) => ({ score, probability: round4(count / nRuns) }));

  return {
    topScorelines,
    mostLikelyScoreline: topScorelines[0].score,
    bttsProbability: round4(btts / nRuns),
    over25Probability: round4(over25 / nRuns),
    under25Probability: round4(1 - over25 / nRuns),
    homeCleanSheetProbability: round4(homeCS / nRuns),
    awayCleanSheetProbability: round4(awayCS / nRuns),
    outcomeProbs: {
      home: round4(homeWins / nRuns),
      draw: round4(draws / nRuns),
      away: round4(awayWins / nRuns),
    },
  };
}

function blend(probsList, weights) {
  const blended = { home: 0, draw: 0, away: 0 };
  probsList.forEach((probs, i) => {
    for (const k in blended) blended[k] += probs[k] * weights[i];
  });
  const total = blended.home + blended.draw + blended.away;
  return { home: round4(blended.home / total), draw: round4(blended.draw / total), away: round4(blended.away / total) };
}

function confidenceScore(probs, penalty) {
  const sorted = Object.values(probs).sort((a, b) => b - a);
  const margin = sorted[0] - sorted[1];
  const raw = 0.5 + margin;
  return Math.round(Math.max(0.3, Math.min(0.97, raw - penalty)) * 1000) / 1000;
}

function anytimeScorers(team, teamLambda) {
  return team.scorers.slice(0, 3).map((s) => ({
    player: s.player,
    anytimeScorerProbability: round4(1 - Math.exp(-teamLambda * s.share)),
  }));
}

function firstGoalscorers(homeTeam, awayTeam, homeLambda, awayLambda) {
  const total = homeLambda + awayLambda;
  if (total === 0) return [];
  const pHomeFirst = homeLambda / total;
  const pAwayFirst = 1 - pHomeFirst;
  const results = [];
  homeTeam.scorers.slice(0, 3).forEach((s) => {
    results.push({ player: s.player, firstGoalscorerProbability: round4(pHomeFirst * s.share) });
  });
  awayTeam.scorers.slice(0, 3).forEach((s) => {
    results.push({ player: s.player, firstGoalscorerProbability: round4(pAwayFirst * s.share) });
  });
  return results.sort((a, b) => b.firstGoalscorerProbability - a.firstGoalscorerProbability);
}

function buildFactors(prediction, homeTeam, awayTeam) {
  const factor = (vh, va, label) => {
    const diff = vh - va;
    return { factor: label, magnitude: Math.round(Math.abs(diff) * 1000) / 1000, favors: diff > 0 ? "home" : diff < 0 ? "away" : "neutral" };
  };
  const factors = [
    factor(homeTeam.elo, awayTeam.elo, "Team strength (Elo rating)"),
    factor(homeTeam.form.ppg, awayTeam.form.ppg, "Recent form (points per game)"),
    factor(prediction.expectedGoals.home, prediction.expectedGoals.away, "Expected goals (attack vs defense matchup)"),
    factor(homeTeam.form.gf_avg, homeTeam.form.ga_avg, `${homeTeam.name} scoring vs conceding trend`),
    factor(awayTeam.form.gf_avg, awayTeam.form.ga_avg, `${awayTeam.name} scoring vs conceding trend`),
  ];
  factors.sort((a, b) => b.magnitude - a.magnitude);
  return factors;
}

function explanation(prediction, homeTeam, awayTeam, factors) {
  const outcomeText = { home: `${homeTeam.name} to win`, away: `${awayTeam.name} to win`, draw: "a draw" }[prediction.predictedOutcome];
  const top = factors[0];
  const favored = top.favors === "home" ? homeTeam.name : top.favors === "away" ? awayTeam.name : "neither side";
  const p = prediction.outcomeProbabilities;

  let text = `Diski Logue favors ${outcomeText} (Home ${Math.round(p.home * 100)}% / Draw ${Math.round(p.draw * 100)}% / Away ${Math.round(p.away * 100)}%), with a confidence score of ${prediction.confidence.toFixed(2)}. `;
  text += `The strongest factor is '${top.factor}', which leans toward ${favored}. `;
  text += `Expected goals: ${homeTeam.name} ${prediction.expectedGoals.home} — ${prediction.expectedGoals.away} ${awayTeam.name}. Most likely scoreline: ${prediction.mostLikelyScoreline}.`;
  if (prediction.confidence < 0.55) {
    text += " Confidence is relatively low — the two sides are closely matched and/or one team has limited recent match history, which increases unpredictability.";
  }
  return text;
}

function round4(x) {
  return Math.round(x * 10000) / 10000;
}

/** Main entry point: predict a fixture between two teams from the season dataset. */
function predictMatch(homeTeam, awayTeam, leagueAvg, nSimulations = 10000) {
  const sProbs = strengthProbs(homeTeam.elo, awayTeam.elo);
  const fProbs = formProbs(homeTeam.form, awayTeam.form);
  const [homeLambda, awayLambda] = expectedGoals(homeTeam, awayTeam, leagueAvg);
  const sim = monteCarloSimulation(homeLambda, awayLambda, nSimulations);

  const outcomeProbabilities = blend([sProbs, fProbs, sim.outcomeProbs], [WEIGHTS.strength, WEIGHTS.form, WEIGHTS.goals]);

  const minMatches = Math.min(homeTeam.form.matches_considered, awayTeam.form.matches_considered);
  const penalty = minMatches >= 5 ? 0 : (5 - minMatches) * 0.03;
  const confidence = confidenceScore(outcomeProbabilities, penalty);

  const predictedOutcome = Object.keys(outcomeProbabilities).reduce((a, b) =>
    outcomeProbabilities[a] > outcomeProbabilities[b] ? a : b
  );

  const prediction = {
    predictedOutcome,
    outcomeProbabilities,
    confidence,
    expectedGoals: { home: Math.round(homeLambda * 100) / 100, away: Math.round(awayLambda * 100) / 100 },
    mostLikelyScoreline: sim.mostLikelyScoreline,
    topScorelines: sim.topScorelines,
    markets: {
      bttsProbability: sim.bttsProbability,
      over25Probability: sim.over25Probability,
      under25Probability: sim.under25Probability,
      homeCleanSheetProbability: sim.homeCleanSheetProbability,
      awayCleanSheetProbability: sim.awayCleanSheetProbability,
    },
    goalscorers: {
      firstGoalscorerTop3: firstGoalscorers(homeTeam, awayTeam, homeLambda, awayLambda).slice(0, 3),
      homeAnytimeScorers: anytimeScorers(homeTeam, homeLambda),
      awayAnytimeScorers: anytimeScorers(awayTeam, awayLambda),
    },
  };

  const factors = buildFactors(prediction, homeTeam, awayTeam);
  prediction.topFactors = factors.slice(0, 5);
  prediction.explanation = explanation(prediction, homeTeam, awayTeam, factors);

  return prediction;
}
