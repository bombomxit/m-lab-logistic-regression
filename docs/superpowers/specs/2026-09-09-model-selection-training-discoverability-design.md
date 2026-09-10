# Model selection and training discoverability design

## Goal

Make the existing upload-to-train flow discoverable and let a learner choose a trained model directly on the Predict page without changing the global active model.

## Scope

- Add a model selector at the top of Predict when one or more model versions exist.
- Selecting a version navigates to `/predict?model_id=<id>` and reloads the form from that model's saved feature metadata.
- The selector clearly marks the active model but does not change it.
- Add a primary `Upload & train model` call-to-action on the dashboard.
- Add explicit `Train` links on the dataset list, pointing to each dataset's existing label-and-feature selection page.
- Clarify the existing Models-page copy: it is a version registry, not the only place to start training.
- Show each model's source dataset, label, feature count, train rows, test rows and total dataset rows.
- Add a read-only, paginated dataset preview route with 50 rows per page and a link to it from each model.
- Add route/template tests for the selector and training links.

## Non-goals

- No separate training route or duplicate training form.
- No change to the active-model semantics.
- No automatic retraining, deletion, model comparison or new ML algorithms.
- No inline spreadsheet editing, CSV export or unbounded rendering of every dataset row.

## User flow

1. Learner sees `Upload & train model` from the dashboard, uploads a CSV, selects label/features and trains.
2. Learner can return to a dataset and use `Train` to create another model version from the same source data.
3. On Predict, the dropdown defaults to the active model. Choosing another version reloads the input controls for that model only.
4. Submitting Predict logs against the selected model as it does today.
5. In Models, learner sees exactly which dataset and how many rows trained/tested each version. `Xem data nguồn` opens a preview of the full source CSV; the displayed split explains that only the training rows were fitted and test rows were held out.
6. Dataset preview shows 50 escaped CSV rows at a time with Previous/Next navigation.

## Technical design

- Reuse `list_models()` in the GET Predict handler and pass versions to the template.
- Render a GET form with a native select for switching models. Its option value is the existing model id and its selected state is the requested/active model.
- Keep the existing POST Predict contract and hidden `model_id` unchanged.
- Reuse existing dataset-detail route for Train links; do not add database or service changes.
- Extend the existing model query with dataset row count and training-job label/feature metadata. Reuse `metrics_json.train_rows` and `metrics_json.test_rows` for the split counts.
- Add a GET dataset-preview route that validates a non-negative page index, reads only the requested CSV window, and renders escaped values through Jinja.
- Generate Previous/Next links only when the requested page exists; cap display length per table cell without changing the underlying CSV.

## Error handling and safety

- A missing or unknown `model_id` continues to use the existing 404 error page with its correct HTTP status.
- The selected model id is loaded server-side before its metadata/form is rendered.
- Switching models is a read-only navigation and cannot activate a version accidentally.
- Preview route only resolves a dataset id stored by the app. It never accepts a file path from the request.
- CSV values are rendered through Jinja auto-escaping and the preview has a fixed 50-row page size.

## Verification

- Predict page shows every model version and identifies the active version.
- Selecting a version renders the correct saved feature names and keeps the requested model id in the POST form.
- Dashboard and dataset list provide train entry points.
- Models cards show the source dataset, label, feature count and train/test/total row counts.
- Dataset preview returns a bounded 50-row page, preserves CSV headers and safely renders text values.
- Existing upload, train and predict regression test passes.

## Scope check

The feature uses existing model metadata, dataset records and CSV files. It adds no model lifecycle state, background job, database table or ML behavior.
