[ (line_comment) (block_comment) (assembly_comment) ] @comment
(assembly_string) @string
[ (number) (assembly_number) ] @number
(boolean) @boolean
(builtin_type) @type.builtin
(type_name) @type

[ "if" "else" "while" "repeat" "break" "goto" "return" "keep"
  "extern" "data" "field" "clobbers" "asm" ] @keyword

[ (arrow) (assignment_operator) "→" "->" "=" "+" "-" "*" "!" "~" "$"
  "&" "|" "^" "&&" "||" "<<" ">>" "==" "!=" "<" "<=" ">" ">=" ] @operator
[ "(" ")" "[" "]" "{" "}" ] @punctuation.bracket
[ "," "." ":" ";" ] @punctuation.delimiter

(procedure name: (identifier) @function)
(external_procedure name: (identifier) @function)
(call function: (_) @function)
(parameter name: (identifier) @variable.parameter)
(access member: (identifier) @property)
(label name: (identifier) @label)
(goto_statement target: (identifier) @label)

((identifier) @constant
  (#match? @constant "^[A-Z][A-Z0-9_]+$"))
((identifier) @variable.special
  (#match? @variable.special "^((AF|BC|DE|HL|[ABCDEHL]|CF|Z|S|PV|HF|N)(_ALT)?|F|IX|IY|SP)$"))

((assembly_word) @variable.special
  (#match? @variable.special "(?i)^((af|bc|de|hl)'?|ix[hl]?|iy[hl]?|sp|[abcdefhilr])$"))
((assembly_word) @keyword
  (#match? @keyword "(?i)^(adc|add|and|bit|call|ccf|cp|cp[di]r?|cpl|daa|dec|di|djnz|ei|ex|exx|halt|im|in|inc|in[di]r?|jp|jr|ld|ld[di]r?|neg|nop|or|ot[di]r|out[di]?|pop|push|res|ret[in]?|rl[ac]?|rlca|rld|rr[ac]?|rrca|rrd|rst|sbc|scf|set|sla|sll|sra|srl|sub|xor)$"))
((assembly_word) @keyword.directive
  (#match? @keyword.directive "(?i)^[.#]?(assert|align|db|dw|ds|def[bdsw]|define|else|endif|endm|equ|extern|if|ifdef|ifndef|incbin|include|macro|org|public|section)$"))
