#!/bin/bash
set -euo pipefail

IMAGE_URL="$1"
VERSION="$2"

if [ -z "$IMAGE_URL" ] || [ -z "$VERSION" ]; then
    echo "Usage: $0 <image-url> <version>"
    exit 1
fi

echo "Submitting openQA job for version $VERSION with image $IMAGE_URL"

# Mock mode for local testing
if [ "${ACT:-false}" == "true" ] || [ "${DRY_RUN:-false}" == "true" ]; then
    echo "Mock Mode: Skipping actual openQA submission."
    echo "Would submit job for $IMAGE_URL"
    echo "Mocking success..."
    exit 0
fi

# Submit the job
# Assuming openqa-cli is configured via environment variables or config file
JOB_ID=$(openqa-cli api -X POST jobs \
    DISTRI=tunaos \
    VERSION="$VERSION" \
    FLAVOR=bootc \
    ARCH=x86_64 \
    TEST=bootc_install \
    HDD_1="$IMAGE_URL" \
    | jq -r .id)

echo "Job submitted: ID $JOB_ID"

# Poll for status
echo "Waiting for job to complete..."
while true; do
    STATE=$(openqa-cli api jobs/"$JOB_ID" | jq -r .state)
    RESULT=$(openqa-cli api jobs/"$JOB_ID" | jq -r .result)

    echo "Job $JOB_ID: State=$STATE, Result=$RESULT"

    if [ "$STATE" == "done" ]; then
        if [ "$RESULT" == "passed" ]; then
            echo "openQA test passed!"
            exit 0
        else
            echo "openQA test failed with result: $RESULT"
            exit 1
        fi
    fi

    sleep 30
done
