# ML Lab Docs and sample CSV design

## Goal

Help a first-time Machine Learning learner understand the full Logistic Regression workflow in the app and immediately practice with safe, fictional binary-classification CSV files.

## Scope

- Add a `Docs` route and navigation item.
- Add a compact learning card on the dashboard that links to `Docs`.
- Explain the workflow: dataset, feature, label, train/test split, probability, threshold, metrics, confusion matrix and prediction.
- Provide three UTF-8 CSV samples with a binary label and a mixture of numeric and categorical features.
- Add direct download links and a small exercise prompt for each sample.
- Add tests for the Docs route and CSV schema expectations.

## Non-goals

- No model types beyond Logistic Regression.
- No claims that the sample scores generalize to real-world decisions.
- No personal, financial, medical or production data.
- No authenticated documentation CMS or external documentation dependency.

## User experience

The top navigation adds `Docs`. The dashboard adds one short card, `Bắt đầu học Logistic Regression`, linking to `/docs`.

The Docs page is a self-contained lesson with this order:

1. A visual five-step map: CSV -> select label and features -> train -> evaluate -> predict.
2. A plain-language explanation that Logistic Regression estimates the probability of one of two classes; the threshold maps that probability to a displayed class.
3. A glossary for row, feature, label, probability, threshold and active model.
4. A metrics section that explains accuracy, precision, recall, F1 and the two kinds of confusion-matrix mistakes.
5. A practice section with three CSV cards and download links.
6. A caution that small, synthetic data can produce misleadingly high scores.

## Sample data

| File | Label | Features | Lesson |
| --- | --- | --- | --- |
| `customer_churn.csv` | `churned` (`yes`/`no`) | inactive days, support tickets, plan | Numeric plus categorical inputs; customer churn pattern. |
| `marketing_response.csv` | `responded` (`yes`/`no`) | visits, discount rate, channel, membership | Probability of responding to a fictional campaign. |
| `returning_customer.csv` | `returned` (`yes`/`no`) | order count, average spend, favorite category, loyalty tier | Observe how categorical and numeric features combine. |

Every dataset is fictional, has enough rows for the app's train/test split, and does not represent an individual or a real decision.

## Technical design

- Add a GET endpoint that renders `docs.html` from the existing FastAPI/Jinja structure.
- Serve sample CSVs as static, repository-tracked files and link using safe same-origin paths.
- Keep explanatory content static in the template: no database schema or model-service changes.
- Reuse existing base layout and CSS classes; add only scoped Docs styles if the current styles do not cover the information hierarchy.

## Error handling and safety

- Download links reference only files that ship with the app.
- The page explicitly says the sample labels are learning targets, not recommendations or decisions.
- No user-generated content is rendered by the Docs page.

## Verification

- Docs route returns HTTP 200 and includes the five-step workflow and the three downloadable sample names.
- CSV validation test checks UTF-8 decoding, required columns, non-empty values and exactly two label values.
- Existing upload -> train -> predict test continues to pass.
- Visual check at desktop and mobile widths confirms the Docs page is readable and navigation remains usable.

## Scope check

This is a bounded documentation-and-samples feature. It adds no ML algorithms, background jobs, persistence or external services.
