.PHONY: verify phase1 backend-test frontend-test

backend-test:
	./scripts/verify_backend.sh

frontend-test:
	./scripts/verify_frontend.sh

verify: phase1

phase1:
	./scripts/verify_phase1.sh
