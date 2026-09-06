.PHONY: verify backend-test frontend-test

backend-test:
	./scripts/verify_backend.sh

frontend-test:
	./scripts/verify_frontend.sh

verify: backend-test frontend-test
