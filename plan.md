# MTG Super Calculator Plan

## Desired Features
[] simple hypergeometric calculator
[] multivariate hypergeometric calculator
[] grouped multivariate hypergeometric calculator
[] logic for mulligans
[] count probabilities over multiple turns
[] customize number of cards drawn per turn
[] include stats for different thresholds (e.g. chance you draw none of the cards, chance you draw exactly that many, etc.)
[] show how mulligans affect the percentages (i.e. after 1 mulligan, after 2 mulligans, etc.)
[] advanced logic for mulligans (1 card is put on the bottom of the deck for each mulligan, not counting the free mulligan)
[] advanced logic (include conditional statements, as well as logical operators such as OR, AND, XOR, etc.)
[] API functionality with tags (import a decklist from Moxfield or Archidekt and automatically generate probabilities based upon card tags)
[] optimizer function (take all inputs except for population counts and optimize population counts to meet the other input criteria)
[] implement gui elements
[] refactor to become a web app
[] *far future* automatic color-fixing analysis
[] *far future* generic opening hand analysis

## Todo
[] implement all features
[] establish unit tests (especially to catch simple flaws in the logic)
[] optimize performance (place heavy computation in dedicated C/C++ files or Rust)
[] set up project in github
[] publish as an official site
