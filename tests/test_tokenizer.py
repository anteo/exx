import unittest

from exxlang.diagnostics import ExxError
from exxlang.tokenizer import Token, tokenize


class TokenizerTests(unittest.TestCase):
    def test_keywords_have_identifier_boundaries(self):
        self.assertEqual(tokenize("return returned"), [
            Token("keyword", "return", 1), Token("name", "returned", 1),
            Token("eof", "", 1),
        ])

    def test_multichar_operators_remain_single_tokens(self):
        operators = ["→", "->", "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "^="]
        self.assertEqual(tokenize(" ".join(operators)),
                         [Token("punct", op, 1) for op in operators] + [Token("eof", "", 1)])

    def test_apostrophe_belongs_to_shadow_pairs(self):
        pairs = ("AF'", "BC'", "DE'", "HL'")
        self.assertEqual(tokenize(" ".join(pairs)),
                         [Token("shadow_pair", pair, 1) for pair in pairs] + [Token("eof", "", 1)])
        for invalid in ("IX'", "label'", "HL'foo"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ExxError, "unexpected character"):
                tokenize(invalid)

    def test_multiline_comments_and_arguments_preserve_source_lines(self):
        source = "(\r\n0xff, /* text\r\n */ 0b11) // end\r\n0"
        self.assertEqual(tokenize(source), [
            Token("punct", "(", 1), Token("int", "0xff", 2), Token("punct", ",", 2),
            Token("int", "0b11", 3), Token("punct", ")", 3), Token("newline", "\n", 3),
            Token("int", "0", 4), Token("eof", "", 4),
        ])

    def test_lexical_errors_report_the_offending_line(self):
        for fragment, message in [("/* incomplete", "unterminated"), ("@", "unexpected")]:
            with self.subTest(fragment=fragment), self.assertRaisesRegex(ExxError, message) as error:
                tokenize("A\n" + fragment)
            self.assertEqual(error.exception.line, 2)
