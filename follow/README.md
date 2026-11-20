# Follow a docket (not deployed)

`worker.js` checks a reader's Ghost member sign-in and adds or removes the
label "Docket NNNNN" on that member, so nightly alerts can go to the readers
who follow a docket. It is not deployed, and no page links to it yet.

`page.html` is the follow page itself, one HTML card for a Ghost page at
`gapublicservice.org/follow/`. It is not published. Under the Follow button it
has a small note with the steps for the Commission's own docket alerts.

Run the tests with `node --test` in this folder.
