# Live smoke checks

Use these checks after a deployment. The automated tests cover the API with synthetic data and mocked providers; these checks confirm that the hosted service and its external providers work together.

- [ ] Open the home page and confirm movie, TV, and anime rows load without a persistent error.
- [ ] Search for a known title and open its detail page.
- [ ] Request a MovieLens recommendation and confirm the suggestions display.
- [ ] Register a disposable test account, log out, then log back in.
- [ ] Add a title to a watchlist, change its status, and remove it.
- [ ] Confirm the same watchlist appears after a page refresh.
- [ ] Open browser developer tools and check for failed requests or console errors.

Use a test account rather than a personal account. Delete its test data when finished. GitHub Pages supports only the static MovieLens preview, so run the account and live-catalogue checks against the Python-hosted site.
