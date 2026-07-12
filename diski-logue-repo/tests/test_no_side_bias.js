/* Regression test for the "right side always wins" class of bug.
   Run: node tests/test_no_side_bias.js
   (run from docs/, or adjust the require path below)

   Checks, over every pair of teams in the sample dataset:
     1. Swapping which team is "home" flips the favored outcome whenever
        the underlying strength gap is decisive (no fixed-side bias).
     2. A team consistently rated stronger (elo, form, attack) is favored
        regardless of which dropdown slot it's placed in.
*/
const fs = require('fs');
const path = require('path');

const engineSrc = fs.readFileSync(path.join(__dirname, '..', 'docs', 'predict-engine.js'), 'utf8');
eval(engineSrc);

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'docs', 'data', 'manifest.json'), 'utf8'));
const sampleEntry = manifest.competitions.find((c) => c.code === 'SAMPLE') || manifest.competitions[0];
const season = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'docs', sampleEntry.file), 'utf8'));
const teams = season.teams;

let checked = 0;
let failures = [];

for (let i = 0; i < teams.length; i++) {
  for (let j = 0; j < teams.length; j++) {
    if (i === j) continue;
    const a = teams[i], b = teams[j];

    // Only test pairs with a clear strength gap — near-even matchups are
    // expected to be close either way, that's not a bug.
    if (Math.abs(a.elo - b.elo) < 80) continue;

    const stronger = a.elo > b.elo ? a : b;
    const weaker = a.elo > b.elo ? b : a;

    const predStrongHome = predictMatch(stronger, weaker, season.league_avg_goals, 4000);
    const predStrongAway = predictMatch(weaker, stronger, season.league_avg_goals, 4000);

    checked++;

    // Stronger team should be favored (highest single probability) whichever
    // slot it's in.
    const strongFavoredAsHome = predStrongHome.predictedOutcome === 'home';
    const strongFavoredAsAway = predStrongAway.predictedOutcome === 'away';

    if (!strongFavoredAsHome || !strongFavoredAsAway) {
      failures.push({
        stronger: stronger.name, weaker: weaker.name,
        eloGap: Math.round(stronger.elo - weaker.elo),
        asHomeProbs: predStrongHome.outcomeProbabilities,
        asAwayProbs: predStrongAway.outcomeProbabilities,
      });
    }
  }
}

console.log(`Checked ${checked} strongly-mismatched pairings in both slot orders.`);
if (failures.length === 0) {
  console.log('PASS — no side bias detected; predictions track team strength, not dropdown position.');
} else {
  console.log(`FAIL — ${failures.length} case(s) where the stronger team was not favored:`);
  console.log(JSON.stringify(failures, null, 2));
  process.exit(1);
}
