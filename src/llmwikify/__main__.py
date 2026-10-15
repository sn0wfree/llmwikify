"""Allow running llmwikify as a module: python3 -m llmwikify"""

import sys

from llmwikify.interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
