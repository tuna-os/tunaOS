# Contributor-owned desktop experiences

Each directory here is a small, reviewable layer of opinionated defaults for
one desktop. It is copied after that desktop's packages are installed by the
manifest-driven installer. It is intentionally not an RPM/DEB: these are
configuration files, not independently versioned software.

To maintain an experience, edit `experiences/<desktop>/files/`, update its
README with the behavior and upstream rationale, and add a focused check under
`tests/`. Desktop maintainers are invited to own reviews for their directory;
until a GitHub team is established, ownership remains open and the project lead
reviews changes.
