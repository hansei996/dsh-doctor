.PHONY: test demo fix-dry lint

test:
	python3 -m unittest discover -s tests -t . -v

demo:
	python3 -m dsh_doctor

fix-dry:
	python3 -m dsh_doctor --fix --dry-run

lint:
	python3 -m compileall -q dsh_doctor
