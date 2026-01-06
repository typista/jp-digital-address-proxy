<?php

$finder = PhpCsFixer\Finder::create()
    ->in(__DIR__ . '/php')
    ->notName('docker-entrypoint.sh');

return (new PhpCsFixer\Config())
    ->setRiskyAllowed(true)
    ->setRules([
        '@PSR12' => true,
        'braces' => [
            'position_after_functions_and_oop_constructs' => 'same',
            'position_after_control_structures' => 'same',
            'allow_single_line_closure' => false,
        ],
    ])
    ->setFinder($finder);
