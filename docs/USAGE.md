# How to use the MTG odds calculator

This app answers questions like:

- *"How often will I have 3 lands by turn 3?"*
- *"Should I play 23 or 24 lands?"*
- *"Is it worth mulliganing a 2-land hand?"*

You describe your deck and what a good game looks like. The app tells you how often that happens. The answers are **calculated exactly** from your deck's numbers. Nothing is guessed, and games are only simulated if you ask for that in Settings.

> Want to type rules by hand or use the calculator from Python? That's covered in [`REFERENCE.md`](REFERENCE.md). You don't need it to use the app.

---

## Opening the app

In a terminal, from the project folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/mtgcalc-gui
```

The app is built on Tkinter, which comes with Python. On Debian or Ubuntu, if it won't start, install Tkinter with `sudo apt install python3-tk`.

---

## A two-minute tour

1. Open **Examples** (top-left menu) and choose **60-card deck: lands and removal by turn 3**.
   - The left side fills in: a 60-card deck with 24 land and 6 removal, and you go first.
2. On the right, the **What are my chances?** tab is open.
   - It already says: *A good game is when I have: at least 3 land by turn 3, and at least 1 removal by turn 3.*
3. Press **Answer**. You'll see:

   > **You have at least 3 land by turn 3 and at least 1 removal by turn 3 in 47.7% of games (about 5 games in 10).**

4. Now change *removal* from 6 to 8 on the left and press **Answer** again to see the difference.

That's the whole idea: change the deck, ask again, compare. Hover over any field for an explanation.

---

## Step 1: Your deck

**Format buttons.** **60-card**, **40-card Limited** and **Commander** set the deck size and the usual rules for that format:
- **Commander** uses 99 cards, because your commander isn't shuffled into the deck.
- It also sets *everyone draws on turn 1* and *first mulligan is free*.

**Cards in your deck.** How many cards you shuffle.

You can describe the deck in one of two ways.

### List card types (best for "what if" questions)

List only the kinds of cards you care about, with how many you play:

| Card type | How many | Also counts as |
|---|---|---|
| land | 24 | |
| removal | 6 | |
| mdfc | 2 | land, removal |

- **Card type** is any name you like: `land`, `ramp`, `removal`, `bomb`, or a specific card such as `sol ring`.
- **Also counts as** is for cards that are more than one thing. Above, the 2 "mdfc" cards (spells that can also be played as a land) count as an *mdfc*, as a *land* and as *removal*. So this deck has 26 cards that count as land.
- Every card you don't list is an **other card**. In the example above that's 60 − 32 = 28 cards.

### Import a deck link

Choose **Decklist or link**, paste the link to a deck into **Deck link**, and press **Import**:

```text
https://archidekt.com/decks/123456/my-deck
```

- **Archidekt** decks (public ones) are downloaded straight away. The cards appear in the box below, and each card's Archidekt categories become its tags. The bottom of the window shows what was imported, for example *Imported 'My deck' from Archidekt: 99 cards in the deck; commander ...; 14 tags (...)*.
- **Moxfield** doesn't allow other programs to download decks. In Moxfield, open the deck, choose **Export → Copy as plain text**, and paste that into the box. Your Moxfield tags come along.
- Imported decks are ordinary text, so you can check them and change tags before asking anything. Tags with spaces become hyphenated (`mana rock` → `#mana-rock`).

### Paste a decklist

Choose **Decklist or link** and paste (or **Open file...**) a list with one card per line. To group cards, add **tags** with `#`:

```text
Commander
1 Atraxa, Praetors' Voice

Deck
36 Forest #land
1 Sol Ring #ramp
9 Arcane Signet #ramp
10 Divination #draw
43 Bear
```

- Lists exported from Moxfield (`#tags`) and Archidekt (`[Categories]`) both work.
- A **Commander** section is kept out of the deck. **Sideboard** and **Maybeboard** sections are ignored.
- You ask questions about the tags (`land`, `ramp`, `draw`). Untagged cards are "other cards".

---

## Step 2: How you play

**I go first / I draw on turn 1.** The player who goes first skips their first draw. In multiplayer games (like Commander) nobody skips it, so choose *I draw on turn 1*.

**Cards drawn each turn.** Normally 1.

**Extra cards drawn.** Use this for card draw you can count on, for example *On turn 3 draw 2 extra* for a draw-two spell on turn 3.

### Mulligans (optional)

Tick **I mulligan bad opening hands** to include mulligans. A **mulligan** means: shuffle your hand away and draw 7 new cards. Then, for each mulligan you've taken, put 1 card from your hand on the bottom of your deck.

| Setting | What it means |
|---|---|
| **Keep a hand with 2 to 5 land** | Which hands you're happy with. Any other hand gets mulliganed. *Keep any hand* means you never mulligan. |
| **When I put cards on the bottom, I keep these first** | Which cards you hold on to when you must put some on the bottom. Put the most important at the top. |
| **keep up to 3** | Hold on to at most 3 of that type. Extras may go to the bottom. |
| **Mulligan at most 2 times** | After the last mulligan you keep whatever you draw. |
| **My first mulligan is free** | The multiplayer rule: the first mulligan costs no card. |

**How bottoming works, with an example.** Say your list is *land, keep up to 3*, then *removal, keep up to 1*. After one mulligan you draw 5 land, 1 removal and 1 other card, and must put 1 on the bottom:
1. Cards you didn't list go first, so the **other card** goes to the bottom.
2. If you had to put a second card on the bottom, it would be a land beyond the 3 you protect.
3. Only after that would protected cards go, with the least important type first.

---

## Describing a good game

Most questions ask you to describe **a good game** as a few lines:

```text
[at least] [3] [land]    [turn 3]
[at least] [1] [removal] [turn 3]
I need (•) all of these  ( ) any one of these
```

| Part | Choices |
|---|---|
| First box | **at least**, **at most**, **exactly**, or **none** (none of that type) |
| Number | How many |
| Card type | Any type from step 1, or **any card** |
| When | **opening hand** (the 7 cards you keep) or **turn N**, meaning *after you draw on turn N* |
| All / any | *All of these* means every line must happen. *Any one of these* means at least one line must. |

**Going first, "by turn 3" means 9 cards:** your 7-card hand plus the draws on turns 2 and 3. Going second it's 10 cards.

**Type my own rule instead (advanced)** turns your lines into a typed rule that you can edit, for example `land >= 3 @T3 AND removal >= 1 @T3`. You never need it, but it allows things the lines can't express. See [`REFERENCE.md`](REFERENCE.md).

---

## The five questions

### 1. What are my chances?

How often a good game happens.

> **You have at least 3 land by turn 3 and at least 1 removal by turn 3 in 47.7% of games (about 5 games in 10).**

**Only count games where...** (optional) narrows the question to some games. For example: *in the games where my opening hand has at least 2 land, how often do I get there?*

> **In the games where you have at least 2 land in your opening hand, you have [...] 53.9% of the time.**
> Those games are 85.7% of all games; both things happen together in 46.2% of all games.

If mulligans are turned on in step 2, the answer covers whole games, including the ones where you mulligan.

### 2. How many will I draw?

Pick a card type and a last turn. For each turn you get the average, and when you click a turn, the chance of each number. For example, 24 land in 60 cards, by turn 3:

| | Exactly this many | This many or more | This many or fewer |
|---|---|---|---|
| 2 land | 15.6% | 94.5% | 21.1% |
| 3 land | 26.7% | 78.9% | 47.8% |
| 4 land | 27.1% | 52.2% | 74.9% |

How to read the columns:
- **This many or more** answers "do I have *enough*?"
- **This many or fewer** answers "am I *flooding*?"

### 3. Turn by turn

How a chance grows from turn to turn. The turns in your lines are ignored here; every turn is shown instead.

| When | Cards seen | Chance of at least 4 land |
|---|---|---|
| Opening hand | 7 | 27.9% |
| Turn 3 | 9 | 52.2% |
| Turn 6 | 12 | 80.3% |

**Cards seen** means your opening hand plus every card drawn so far.

### 4. Should I mulligan?

This question needs mulligans turned on in step 2. It compares three ways of playing:

> **With your mulligan plan you get a good game 54.1% of the time. Never mulliganing: 47.7%. The best possible plan: 74.9%.**

- **Your plan** follows your keep rule from step 2.
- **Never mulliganing** keeps whatever 7 cards you draw.
- **The best possible plan** is the best any keep-or-mulligan choice could do with your bottoming order. If it's much higher than your plan, your keep rule could be better.

**Reading the table.** Under **Your plan**, each step shows:
- **Get here:** how often you mulligan this far.
- **Keep it:** how often you keep the hand at this step.
- **Good game if kept:** your chance of a good game if you keep the hand.

Under **Best possible plan**, each step shows a simple rule, such as:

> **First 7 cards: keep if its chance is at least 65.1%**

That 65.1% is what you'd get on average by mulliganing instead. Open a step to see every possible hand (for example *3 land, 1 removal, 3 other -> keep*), how often you draw it, and its chance of a good game. Only the card types used in your question are named; everything else is shown as "other".

### 5. How many should I play?

Let the app choose the counts. It tries different numbers for the card types you pick. **Every other card type keeps its number from step 1**, and the rest of the deck is other cards. Choose one of three questions:

| Question | Example answer |
|---|---|
| **How many of one card type do I need to reach a target chance?** | *Play 33 land: you then have at least 4 land by turn 4 in 91.8% of games, which reaches your 90.0% target. With 32 land it would be 89.9%.* |
| **How should I share a number of card slots between card types?** You set *Card slots to share*: how many cards those types may use in total. | *Best use of 30 cards: 22 land, 8 removal.* |
| **What is the fewest cards of these types that reach a target chance?** | *The fewest cards that reach 50.0%: ...* |

For each card type, *from ... to ...* sets the range to try.

Under the answer you'll see one of two notes:
- *This is guaranteed to be the best answer.* The app checked every option, or proved the others can't win.
- *...the best one found by a smart search.* There were too many options to check them all, so the answer is very likely, but not certainly, the best.

If you see **"cannot be reached"**, one of these will help:
- Raise the *to* numbers.
- Lower the target.
- Add the other card types your good game needs to the list. If your good game needs removal but only land may change, extra land can't help with the removal.

---

## Settings

Most people never need these.

| Setting | Effect |
|---|---|
| **Calculate exactly** (recommended) | Precise answers |
| **Simulate games** | Plays many random games instead. Answers show a range, e.g. *very likely between 47.3% and 48.1%*. |
| **Calculate exactly, but simulate if a question is too big** | A safety net for huge questions |
| **Also show exact fractions** | Shows e.g. *33.3% (= 1/3)* |

---

## Common questions

**Why isn't "3 lands by turn 3 and 1 removal by turn 3" just the two chances multiplied?**
They aren't independent. Drawing more lands leaves fewer slots for removal. The app works out the combined chance exactly.

**Why does one card count twice?**
A card counts for every type it has, so a land that can also be removal counts as both. If you need different cards for each thing (3 lands *and* a separate removal spell), use a typed rule with `assign(...)`. See [`REFERENCE.md`](REFERENCE.md).

**What does "less than 0.001%" mean?**
It can happen, but extremely rarely.

**Does it simulate games?**
Not unless you choose that in Settings. Answers are exact.

**Importing says "Deck not found" or "refused".**
The deck must be public. Open the link in your browser to check it works, then try again.

**The window says "Please check your deck".**
The message after the colon says what's wrong, for example *the card types add up to 65, more than the 60 cards*.

---

## Words used in the app

| Word | Meaning |
|---|---|
| Card type | A kind of card you named (land, ramp, removal...) |
| Also counts as | Extra types a card has; it counts for each of them |
| Other cards | Cards you didn't give a type |
| Opening hand | The 7 cards you start with, after any mulligans |
| By turn 3 | After you draw on turn 3 |
| Going first | You skip the draw on your first turn |
| Mulligan | Redrawing a bad hand and putting 1 card on the bottom per mulligan |
| Keep first | Which cards you protect when putting cards on the bottom |
| Good game | Whatever you described in the question |
| Best possible plan | The best any keep-or-mulligan choice could do |
| Guaranteed best / best found | Checked everything / searched smartly but couldn't check everything |
